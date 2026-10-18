from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime
from threading import Barrier
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from tests.support.billing_services import BillingSetup
from tests.support.payments import PaymentSetup, provision_payment

from backend_app.integrations.wechatpay.client import identity_digest
from backend_app.integrations.wechatpay.payments import PaymentFact
from backend_app.models.admin import utc_now
from backend_app.models.billing import Bill, BillOperation, BillSettlementEntry
from backend_app.models.housing import House
from backend_app.models.miniapp import MiniappUser
from backend_app.models.payments import (
    BillPaymentReservation,
    PaymentChannelNotification,
    PaymentChannelRequest,
    PaymentOrder,
    PaymentOrderItem,
    PaymentTask,
    PaymentUnfreezeOrder,
    ProfitSharingAllocation,
    ProfitSharingOrder,
    PropertyMerchantBinding,
)
from backend_app.models.property import PropertyCompany
from backend_app.repositories.payments.funds import FundsRepository
from backend_app.repositories.payments.tasks import TaskLease, claim_tasks, ensure_task
from backend_app.services.worker.payments.confirmation import (
    ConfirmationService,
    PaymentConfirmationError,
)


def _required[T](value: T | None) -> T:
    assert value is not None
    return value


def scenario(setup: BillingSetup, *, rate: int = 300) -> PaymentSetup:
    bill_id = setup.create().bill.id
    with setup.factory() as db:
        payment = provision_payment(db, setup, bill_id=bill_id, rate_bps=rate)
        db.commit()
    return payment


def fact_for(db: Session, payment: PaymentSetup, now: datetime) -> PaymentFact:
    order = _required(db.get(PaymentOrder, payment.order_id))
    binding = db.get(PropertyMerchantBinding, payment.binding_id)
    payer = db.get(MiniappUser, payment.payer_user_id)
    assert order is not None and binding is not None and payer is not None
    return PaymentFact(
        binding.service_provider_merchant_no,
        binding.merchant_no,
        "wx_test_app",
        order.order_no,
        "SUCCESS",
        "transaction_" + order.id,
        order.amount_cents,
        order.amount_cents - 1,
        "CNY",
        identity_digest(payer.wechat_openid),
        now,
    )


def query_source(
    db: Session, payment: PaymentSetup, fact: PaymentFact, now: datetime
) -> tuple[str, TaskLease]:
    source = PaymentChannelRequest(
        operation="payment_query",
        payment_order_id=payment.order_id,
        request_snapshot={"order_no": fact.order_no},
        outcome="verified_response",
        http_status=200,
        response_snapshot=fact.snapshot(),
        request_id="query",
        finished_at=now,
    )
    db.add(source)
    db.flush()
    ensure_task(db, "payment_query", payment.order_id, now=now)
    leases = claim_tasks(db, now=now, task_types={"payment_query"})
    assert len(leases) == 1
    return source.id, leases[0]


@pytest.mark.parametrize("rate", [300, 0])
def test_confirmation_commits_posting_and_initial_funds_in_one_transaction(
    billing_setup: BillingSetup, rate: int
) -> None:
    payment = scenario(billing_setup, rate=rate)
    now = utc_now()
    with billing_setup.factory() as db:
        fact = fact_for(db, payment, now)
        source_id, lease = query_source(db, payment, fact, now)
        db.commit()
    service = ConfirmationService(billing_setup.factory, app_id="wx_test_app", clock=lambda: now)
    assert service.confirm(payment.order_id, fact, source_request_id=source_id, lease=lease)
    assert not service.confirm(payment.order_id, fact, source_request_id=source_id)
    with billing_setup.factory() as db:
        order = _required(db.get(PaymentOrder, payment.order_id))
        item = db.get(PaymentOrderItem, payment.item_id)
        assert order is not None and order.status == "succeeded" and item is not None
        bill = db.get(Bill, item.bill_id)
        assert bill is not None and bill.settled_cents == 10000 and bill.row_version == 2
        assert order.payer_total_cents == 9999
        assert db.get(BillPaymentReservation, item.bill_id) is None
        task = db.get(PaymentTask, lease.id)
        assert task is not None and task.status == "completed"
        assert db.scalar(select(func.count()).select_from(BillSettlementEntry)) == 1
        if rate:
            assert db.scalar(select(ProfitSharingAllocation.amount_cents)) == 300
            sharing = _required(db.scalar(select(ProfitSharingOrder)))
            assert sharing is not None
            next_task = db.scalar(
                select(PaymentTask).where(PaymentTask.profit_sharing_order_id == sharing.id)
            )
            assert next_task is not None and next_task.next_run_at > now
        else:
            assert db.scalar(select(func.count()).select_from(ProfitSharingAllocation)) == 0
            assert db.scalar(select(func.count()).select_from(PaymentUnfreezeOrder)) == 1


def test_funds_failure_rolls_back_all_business_facts_but_keeps_durable_source(
    billing_setup: BillingSetup, monkeypatch: pytest.MonkeyPatch
) -> None:
    payment = scenario(billing_setup)
    now = utc_now()
    with billing_setup.factory() as db:
        fact = fact_for(db, payment, now)
        source_id, lease = query_source(db, payment, fact, now)
        db.commit()
    original = FundsRepository.initialize_funds

    def fail(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("injected funds failure")

    monkeypatch.setattr(FundsRepository, "initialize_funds", fail)
    service = ConfirmationService(billing_setup.factory, app_id="wx_test_app", clock=lambda: now)
    with pytest.raises(RuntimeError, match="injected funds failure"):
        service.confirm(payment.order_id, fact, source_request_id=source_id, lease=lease)
    with billing_setup.factory() as db:
        order = _required(db.get(PaymentOrder, payment.order_id))
        item = db.get(PaymentOrderItem, payment.item_id)
        assert order is not None and order.status == "pending" and item is not None
        assert db.get(BillPaymentReservation, item.bill_id) is not None
        assert db.scalar(select(func.count()).select_from(BillOperation)) == 1
        assert db.scalar(select(func.count()).select_from(BillSettlementEntry)) == 0
        assert db.get(PaymentChannelRequest, source_id) is not None
    monkeypatch.setattr(FundsRepository, "initialize_funds", original)
    assert service.confirm(payment.order_id, fact, source_request_id=source_id, lease=lease)


@pytest.mark.parametrize(
    "change",
    [
        {"merchant_no": "wrong"},
        {"service_provider_merchant_no": "wrong"},
        {"app_id": "wrong"},
        {"amount_cents": 1},
        {"order_no": "wrong"},
        {"payer_identity_digest": "wrong"},
        {"currency": "USD"},
        {"channel_status": "NOTPAY"},
    ],
)
def test_confirmation_rejects_business_mismatch_without_releasing_reservation(
    billing_setup: BillingSetup, change: dict[str, Any]
) -> None:
    payment = scenario(billing_setup)
    now = utc_now()
    with billing_setup.factory() as db:
        fact = replace(fact_for(db, payment, now), **change)
        source_id, lease = query_source(db, payment, fact, now)
        db.commit()
    service = ConfirmationService(billing_setup.factory, app_id="wx_test_app", clock=lambda: now)
    with pytest.raises(PaymentConfirmationError, match="PAYMENT_FACT_MISMATCH"):
        service.confirm(payment.order_id, fact, source_request_id=source_id, lease=lease)
    with billing_setup.factory() as db:
        assert db.scalar(select(func.count()).select_from(BillPaymentReservation)) == 1
        assert db.scalar(select(func.count()).select_from(BillSettlementEntry)) == 0


def test_current_company_house_and_user_disable_does_not_reject_historical_success(
    billing_setup: BillingSetup,
) -> None:
    payment = scenario(billing_setup)
    now = utc_now()
    with billing_setup.factory() as db:
        fact = fact_for(db, payment, now)
        source_id, lease = query_source(db, payment, fact, now)
        company = db.get(PropertyCompany, billing_setup.housing.company_id)
        house = db.get(House, billing_setup.house_id)
        payer = db.get(MiniappUser, payment.payer_user_id)
        assert company is not None and house is not None and payer is not None
        company.enabled = False
        house.enabled = False
        payer.enabled = False
        db.commit()
    assert ConfirmationService(
        billing_setup.factory, app_id="wx_test_app", clock=lambda: now
    ).confirm(payment.order_id, fact, source_request_id=source_id, lease=lease)


def test_notification_and_query_race_posts_once_and_finishes_both_tasks(
    billing_setup: BillingSetup,
) -> None:
    payment = scenario(billing_setup)
    now = utc_now()
    with billing_setup.factory() as db:
        fact = fact_for(db, payment, now)
        source_id, query_lease = query_source(db, payment, fact, now)
        notification = PaymentChannelNotification(
            channel_notification_id="notification",
            notification_type="payment_success",
            payload=fact.snapshot(),
        )
        db.add(notification)
        db.flush()
        notification_id = notification.id
        ensure_task(db, "notification_process", notification.id, now=now)
        notification_lease = claim_tasks(db, now=now, task_types={"notification_process"})[0]
        db.commit()
    barrier = Barrier(2)

    def confirm(kind: str) -> bool:
        service = ConfirmationService(
            billing_setup.factory, app_id="wx_test_app", clock=lambda: now
        )
        barrier.wait(timeout=10)
        if kind == "query":
            return service.confirm(
                payment.order_id, fact, source_request_id=source_id, lease=query_lease
            )
        return service.confirm(
            payment.order_id, fact, notification_id=notification_id, lease=notification_lease
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(confirm, ("query", "notification")))
    assert sorted(results) == [False, True]
    with billing_setup.factory() as db:
        assert db.scalar(select(func.count()).select_from(BillSettlementEntry)) == 1
        assert db.scalar(select(func.count()).select_from(ProfitSharingAllocation)) == 1
        assert db.scalar(select(func.count()).select_from(ProfitSharingOrder)) == 1
        notification = _required(db.get(PaymentChannelNotification, notification_id))
        assert notification is not None and notification.status == "processed"
        for lease in (query_lease, notification_lease):
            task = db.get(PaymentTask, lease.id)
            assert task is not None and task.status == "completed"
