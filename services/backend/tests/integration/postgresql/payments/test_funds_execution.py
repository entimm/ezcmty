import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Event
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select
from tests.support.billing_services import BillingSetup
from tests.support.payments import PaymentSetup, complete_payment, provision_payment
from tests.support.wechatpay import WechatPayHarness

from backend_app.domain.payments.funds import FundsBlocked
from backend_app.integrations.wechatpay.profit_sharing import ProfitSharing
from backend_app.models.admin import utc_now
from backend_app.models.payments import (
    PaymentChannelNotification,
    PaymentChannelRequest,
    PaymentOrder,
    PaymentTask,
    PaymentUnfreezeOrder,
    ProfitSharingAllocation,
    ProfitSharingOrder,
    ProfitSharingOrderItem,
    ProfitSharingRuleVersionItem,
)
from backend_app.repositories.payments.channel_records import store_notification
from backend_app.repositories.payments.funds import FundsRepository
from backend_app.repositories.payments.tasks import LeaseLost, TaskLease, claim_tasks
from backend_app.services.worker.payments.profit_notifications import ProfitNotificationService
from backend_app.services.worker.payments.profit_sharing import ProfitSharingService
from backend_app.services.worker.payments.unfreezing import UnfreezingService


def _required[T](value: T | None) -> T:
    assert value is not None
    return value


def setup_payment(setup: BillingSetup, *, rates: tuple[int, ...] = (300,)) -> PaymentSetup:
    bill = setup.create().bill.id
    with setup.factory() as db:
        payment = provision_payment(db, setup, bill_id=bill, rates=rates)
        complete_payment(db, payment, paid_at=utc_now() - timedelta(minutes=2))
        db.commit()
    return payment


def claim(setup: BillingSetup, now: datetime, *types: str) -> TaskLease:
    with setup.factory() as db:
        leases = claim_tasks(db, now=now, task_types=types, lease_seconds=30)
        assert len(leases) == 1
        db.commit()
        return leases[0]


def sharing_fact(
    setup: BillingSetup,
    execution_id: str,
    now: datetime,
    *,
    results: tuple[str, ...] | None = None,
    unfreeze_amount: int = 9675,
    processing: bool = False,
) -> dict[str, Any]:
    with setup.factory() as db:
        sharing = db.get(ProfitSharingOrder, execution_id)
        order: ProfitSharingOrder | PaymentUnfreezeOrder | None = sharing
        if order is None:
            order = db.get(PaymentUnfreezeOrder, execution_id)
        assert order is not None
        payment = db.get(PaymentOrder, order.payment_order_id)
        assert payment is not None
        if sharing:
            receiver_values = []
            allocations = {a.id: a for a in FundsRepository(db).allocations(payment.id)}
            for item in FundsRepository(db).sharing_items(order.id):
                rule = db.get(
                    ProfitSharingRuleVersionItem,
                    allocations[item.allocation_id].rule_version_item_id,
                )
                assert rule is not None
                receiver_values.append((rule.receiver_account, item.amount_cents))
            receiver_values.sort()
        else:
            receiver_values = [("1900000002", unfreeze_amount)]
        return {
            "sub_mchid": "1900000002",
            "transaction_id": payment.channel_transaction_no,
            "out_order_no": order.order_no,
            "order_id": "channel_" + order.id,
            "state": "PROCESSING" if processing else "FINISHED",
            "receivers": [
                {
                    "type": "MERCHANT_ID",
                    "account": account,
                    "amount": amount,
                    "result": (
                        results[index] if results else ("PENDING" if processing else "SUCCESS")
                    ),
                    "detail_id": "detail_" + str(index),
                    "finish_time": now.isoformat(),
                    "fail_reason": "INSUFFICIENT_BALANCE"
                    if results and results[index] == "CLOSED"
                    else None,
                }
                for index, (account, amount) in enumerate(receiver_values)
            ],
        }


def test_partial_success_retries_only_unfulfilled_then_queries_actual_unfreeze(
    billing_setup: BillingSetup,
) -> None:
    payment = setup_payment(billing_setup, rates=(300, 200))
    now = utc_now()
    peer = WechatPayHarness()
    sent: list[dict[str, Any]] = []
    lease = claim(billing_setup, now, "profit_sharing_submit")
    first = sharing_fact(billing_setup, lease.target_id, now, results=("SUCCESS", "CLOSED"))

    def initial(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        assert sent[-1]["unfreeze_unsplit"] is False
        return peer.response(first)

    ProfitSharingService(
        billing_setup.factory, ProfitSharing(peer.client(initial)), clock=lambda: now
    ).handle(lease)
    with billing_setup.factory() as db:
        orders = FundsRepository(db).sharing_orders(payment.order_id)
        assert len(orders) == 2 and orders[0].status == "finished"
        assert FundsRepository(db).remaining(payment.order_id) == {
            FundsRepository(db).sharing_items(orders[1].id)[0].allocation_id: 200
        }
        assert (
            sum(
                item.result == "success" for item in FundsRepository(db).sharing_items(orders[0].id)
            )
            == 1
        )
    now += timedelta(minutes=2)
    lease = claim(billing_setup, now, "profit_sharing_submit")
    second = sharing_fact(billing_setup, lease.target_id, now)
    ProfitSharingService(
        billing_setup.factory,
        ProfitSharing(peer.client(lambda request: peer.response(second))),
        clock=lambda: now,
    ).handle(lease)
    with billing_setup.factory() as db:
        assert FundsRepository(db).remaining(payment.order_id) == {}
        assert db.scalar(select(func.count()).select_from(ProfitSharingAllocation)) == 2
        unfreeze = db.scalar(select(PaymentUnfreezeOrder))
        assert unfreeze is not None
    lease = claim(billing_setup, now, "unfreeze_submit")
    response = sharing_fact(billing_setup, lease.target_id, now, unfreeze_amount=9471)
    service = UnfreezingService(
        billing_setup.factory,
        ProfitSharing(peer.client(lambda request: peer.response(response))),
        clock=lambda: now,
    )
    service.handle(lease)
    with billing_setup.factory() as db:
        result = db.get(PaymentUnfreezeOrder, lease.target_id)
        assert (
            result is not None and result.status == "processing" and result.unfrozen_cents is None
        )
    now += timedelta(seconds=10)
    lease = claim(billing_setup, now, "unfreeze_query")
    service.handle(lease)
    with billing_setup.factory() as db:
        result = db.get(PaymentUnfreezeOrder, lease.target_id)
        assert result is not None and result.status == "succeeded" and result.unfrozen_cents == 9471
        assert _required(db.get(PaymentOrder, payment.order_id)).status == "succeeded"
        with pytest.raises(FundsBlocked, match="UNFREEZE_BARRIER"):
            FundsRepository(db).create_sharing(
                FundsRepository(db).lock_payment(payment.order_id), now=now
            )


def test_unknown_submit_queries_original_then_retries_same_number_only_after_trusted_not_found(
    billing_setup: BillingSetup,
) -> None:
    payment = setup_payment(billing_setup)
    now = utc_now()
    peer = WechatPayHarness()
    paths: list[tuple[str, str, str | None]] = []

    def timeout(request: httpx.Request) -> httpx.Response:
        paths.append(
            (request.method, request.url.path, json.loads(request.content)["out_order_no"])
        )
        raise httpx.ReadTimeout("isolated timeout", request=request)

    channel = ProfitSharing(peer.client(timeout))
    service = ProfitSharingService(billing_setup.factory, channel, clock=lambda: now)
    lease = claim(billing_setup, now, "profit_sharing_submit")
    original_id = lease.target_id
    service.handle(lease)
    with billing_setup.factory() as db:
        assert _required(db.get(ProfitSharingOrder, original_id)).status == "unknown"
        assert db.scalar(select(func.count()).select_from(ProfitSharingOrder)) == 1
    now += timedelta(seconds=10)

    def not_found(request: httpx.Request) -> httpx.Response:
        paths.append((request.method, request.url.path, None))
        return peer.response({"code": "ORDER_NOT_EXIST", "message": "original absent"}, 404)

    service.channel = ProfitSharing(peer.client(not_found))
    service.handle(claim(billing_setup, now, "profit_sharing_submit"))
    assert paths[-1][0] == "GET" and _required(paths[0][2]) in paths[-1][1]
    now += timedelta(seconds=20)
    response = sharing_fact(billing_setup, original_id, now)

    def accepted(request: httpx.Request) -> httpx.Response:
        paths.append(
            (request.method, request.url.path, json.loads(request.content)["out_order_no"])
        )
        return peer.response(response)

    service.channel = ProfitSharing(peer.client(accepted))
    service.handle(claim(billing_setup, now, "profit_sharing_submit"))
    assert paths[-1][0] == "POST" and paths[-1][2] == paths[0][2]
    with billing_setup.factory() as db:
        assert _required(db.get(ProfitSharingOrder, original_id)).status == "finished"
        assert FundsRepository(db).remaining(payment.order_id) == {}
        assert db.scalar(select(func.count()).select_from(PaymentChannelRequest)) == 3


def test_zero_obligation_no_remaining_is_distinct_from_own_unfreeze_success(
    billing_setup: BillingSetup,
) -> None:
    payment = setup_payment(billing_setup, rates=(0,))
    now = utc_now()
    peer = WechatPayHarness()
    with billing_setup.factory() as db:
        transaction = _required(db.get(PaymentOrder, payment.order_id)).channel_transaction_no

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/amounts"):
            return peer.response({"transaction_id": transaction, "unsplit_amount": 0})
        return peer.response({"code": "NO_UNSPLIT_AMOUNT", "message": "nothing left"}, 400)

    UnfreezingService(
        billing_setup.factory, ProfitSharing(peer.client(handler)), clock=lambda: now
    ).handle(claim(billing_setup, now, "unfreeze_submit"))
    with billing_setup.factory() as db:
        order = _required(db.scalar(select(PaymentUnfreezeOrder)))
        assert order is not None and order.status == "no_remaining" and order.unfrozen_cents is None
        assert db.scalar(select(func.count()).select_from(ProfitSharingAllocation)) == 0
        assert _required(db.get(PaymentOrder, payment.order_id)).status == "succeeded"
        assert (
            FundsRepository(db).recover(FundsRepository(db).lock_payment(payment.order_id), now=now)
            is None
        )


@pytest.mark.parametrize("operation", ["profit_sharing", "unfreeze"])
def test_lost_lease_keeps_trusted_late_evidence_and_takeover_restores_original(
    billing_setup: BillingSetup,
    operation: str,
) -> None:
    payment = setup_payment(billing_setup, rates=(0,) if operation == "unfreeze" else (300,))
    now = utc_now()
    peer = WechatPayHarness()
    lease = claim(billing_setup, now, operation + "_submit")
    fact = sharing_fact(billing_setup, lease.target_id, now)
    started, release = Event(), Event()

    def handler(request: httpx.Request) -> httpx.Response:
        started.set()
        assert release.wait(10)
        return peer.response(fact)

    service_type = UnfreezingService if operation == "unfreeze" else ProfitSharingService
    service = service_type(
        billing_setup.factory, ProfitSharing(peer.client(handler)), clock=lambda: now
    )
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(service.handle, lease)
        assert started.wait(5)
        now += timedelta(seconds=31)
        takeover = claim(billing_setup, now, operation + "_submit")
        release.set()
        with pytest.raises(LeaseLost):
            future.result(timeout=10)
    with billing_setup.factory() as db:
        evidence = db.scalar(select(PaymentChannelRequest))
        assert evidence is not None and evidence.outcome == "verified_response"
    # Saved source applies without another HTTP call; unfreeze still requires its query.
    service.channel = ProfitSharing(
        peer.client(lambda request: pytest.fail("recovery discarded trusted evidence"))
    )
    service.handle(takeover)
    with billing_setup.factory() as db:
        if operation == "unfreeze":
            assert _required(db.get(PaymentUnfreezeOrder, lease.target_id)).status == "processing"
        else:
            assert _required(db.get(ProfitSharingOrder, lease.target_id)).status == "finished"
        assert _required(db.get(PaymentOrder, payment.order_id)).status == "succeeded"


@pytest.mark.parametrize("mismatch", [False, True])
def test_profit_notification_is_only_corroboration_and_queues_whole_original_query(
    billing_setup: BillingSetup,
    mismatch: bool,
) -> None:
    payment = setup_payment(billing_setup)
    now = utc_now()
    with billing_setup.factory() as db:
        sharing = _required(db.scalar(select(ProfitSharingOrder)))
        rule = db.get(ProfitSharingRuleVersionItem, payment.rule_item_ids[0])
        assert sharing is not None and rule is not None
        transaction = _required(db.get(PaymentOrder, payment.order_id)).channel_transaction_no
        notification, _ = store_notification(
            db,
            channel_notification_id="sharing_notice",
            notification_type="profit_sharing",
            payload={
                "service_provider_merchant_no": "1900000001",
                "merchant_no": "1900000002",
                "order_no": sharing.order_no,
                "channel_transaction_no": transaction,
                "channel_order_no": "channel_" + sharing.id,
                "receiver_type": "merchant",
                "receiver_account": rule.receiver_account,
                "amount_cents": 301 if mismatch else 300,
                "finished_at": now.isoformat(),
            },
            now=now,
        )
        notification_id = notification.id
        db.commit()
    ProfitNotificationService(billing_setup.factory, clock=lambda: now).handle(
        claim(billing_setup, now, "notification_process")
    )
    with billing_setup.factory() as db:
        notification = _required(db.get(PaymentChannelNotification, notification_id))
        assert notification is not None and notification.status == (
            "quarantined" if mismatch else "processed"
        )
        assert db.scalar(
            select(func.count())
            .select_from(PaymentTask)
            .where(PaymentTask.task_type == "profit_sharing_query")
        ) == (0 if mismatch else 1)
        assert FundsRepository(db).remaining(payment.order_id) != {}
        assert db.scalar(select(ProfitSharingOrderItem.result)) is None


@pytest.mark.parametrize("operation", ["profit_sharing", "unfreeze"])
def test_definite_insufficient_funds_pauses_and_manual_recovery_preserves_history(
    billing_setup: BillingSetup,
    operation: str,
) -> None:
    payment = setup_payment(billing_setup, rates=(0,) if operation == "unfreeze" else (300,))
    now = utc_now()
    peer = WechatPayHarness()
    channel = ProfitSharing(
        peer.client(
            lambda request: peer.response(
                {"code": "NOT_ENOUGH", "message": "isolated rejection"}, 400
            )
        )
    )
    service_type = UnfreezingService if operation == "unfreeze" else ProfitSharingService
    service = service_type(billing_setup.factory, channel, clock=lambda: now)
    lease = claim(billing_setup, now, operation + "_submit")
    service.handle(lease)
    with billing_setup.factory() as db:
        repository = FundsRepository(db)
        locked = repository.lock_payment(payment.order_id)
        old = (
            db.get(PaymentUnfreezeOrder, lease.target_id)
            if operation == "unfreeze"
            else db.get(ProfitSharingOrder, lease.target_id)
        )
        assert old is not None and old.status == (
            "failed" if operation == "unfreeze" else "rejected"
        )
        task = db.get(PaymentTask, lease.id)
        assert task is not None and task.status == "paused"
        recovery = repository.recover(locked, now=now)
        assert recovery is not None
        original_task_id = recovery.id
        assert _required(repository.recover(locked, now=now)).id == original_task_id
        db.commit()
    with billing_setup.factory() as db:
        assert (
            db.scalar(
                select(func.count()).select_from(
                    PaymentUnfreezeOrder if operation == "unfreeze" else ProfitSharingOrder
                )
            )
            == 2
        )
        assert _required(db.get(PaymentOrder, payment.order_id)).status == "succeeded"
        if operation == "unfreeze":
            with pytest.raises(FundsBlocked, match="UNFREEZE_BARRIER"):
                FundsRepository(db).create_sharing(
                    FundsRepository(db).lock_payment(payment.order_id), now=now
                )


def test_no_remaining_without_trusted_amount_stays_unknown(
    billing_setup: BillingSetup,
) -> None:
    payment = setup_payment(billing_setup, rates=(0,))
    now = utc_now()
    peer = WechatPayHarness()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/amounts"):
            # Even a correctly signed but structurally incomplete body cannot settle the outcome.
            return peer.response({"transaction_id": "not-an-amount"})
        return peer.response({"code": "NO_UNSPLIT_AMOUNT", "message": "nothing left"}, 400)

    UnfreezingService(
        billing_setup.factory, ProfitSharing(peer.client(handler)), clock=lambda: now
    ).handle(claim(billing_setup, now, "unfreeze_submit"))
    with billing_setup.factory() as db:
        order = _required(db.scalar(select(PaymentUnfreezeOrder)))
        assert order is not None and order.status == "unknown" and order.unfrozen_cents is None
        assert order.finished_at is None
        assert _required(db.get(PaymentOrder, payment.order_id)).status == "succeeded"


def test_acceptance_limit_counts_executions_and_keeps_unfulfilled_obligation(
    billing_setup: BillingSetup,
) -> None:
    payment = setup_payment(billing_setup)
    now = utc_now()
    with billing_setup.factory() as db:
        repository = FundsRepository(db)
        locked = repository.lock_payment(payment.order_id)
        order = repository.sharing_orders(payment.order_id)[0]
        for index in range(50):
            order.channel_order_no = f"accepted_{index}"
            order.status = "finished"
            for item in repository.sharing_items(order.id):
                item.result = "failed"
                item.finished_at = now
                item.fail_reason = "INSUFFICIENT_BALANCE"
            db.flush()
            if index < 49:
                created = repository.create_sharing(locked, now=now)
                assert created is not None
                order = created
        with pytest.raises(FundsBlocked, match="SHARING_ACCEPTANCE_LIMIT"):
            repository.create_sharing(locked, now=now)
        assert list(repository.remaining(payment.order_id).values()) == [300]
        assert repository.unfreeze_orders(payment.order_id) == []
        db.commit()


def test_concurrent_manual_recovery_merges_original_task_under_payment_parent(
    billing_setup: BillingSetup,
) -> None:
    payment = setup_payment(billing_setup)
    now = utc_now()

    def recover() -> str:
        with billing_setup.factory() as db:
            repository = FundsRepository(db)
            task = repository.recover(repository.lock_payment(payment.order_id), now=now)
            assert task is not None
            result = task.id
            db.commit()
            return result

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert len(set(pool.map(lambda _: recover(), range(2)))) == 1
    with billing_setup.factory() as db:
        assert db.scalar(select(func.count()).select_from(ProfitSharingOrder)) == 1
        assert (
            db.scalar(
                select(func.count())
                .select_from(PaymentTask)
                .where(PaymentTask.task_type == "profit_sharing_submit")
            )
            == 1
        )


def test_missing_initial_funds_facts_fail_closed_instead_of_assuming_zero_obligation(
    billing_setup: BillingSetup,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payment = setup_payment(billing_setup)
    now = utc_now()
    # Simulate a missing/corrupt historical projection; the live schema independently rejects
    # removal of a committed allocation. Recovery must not interpret absent facts as zero owed.
    monkeypatch.setattr(FundsRepository, "allocations", lambda self, payment_id: [])
    with billing_setup.factory() as db:
        repository = FundsRepository(db)
        with pytest.raises(FundsBlocked, match="INITIAL_FUNDS_FACTS_MISSING"):
            repository.recover(repository.lock_payment(payment.order_id), now=now)
        assert repository.unfreeze_orders(payment.order_id) == []


def test_external_resolution_requires_normal_recovery_for_unfreeze_not_yet_created(
    billing_setup: BillingSetup,
) -> None:
    from backend_app.models.payments import PaymentReconciliationDiscrepancy
    from backend_app.services.platform_admin.payment_recovery import PaymentRecoveryService

    payment = setup_payment(billing_setup)
    now = utc_now()
    with billing_setup.factory() as db:
        repository = FundsRepository(db)
        locked = repository.lock_payment(payment.order_id)
        sharing = repository.sharing_orders(payment.order_id)[0]
        sharing.status = "finished"
        sharing.channel_order_no = "accepted_sharing"
        for item in repository.sharing_items(sharing.id):
            item.result = "success"
            item.channel_detail_no = "accepted_detail"
            item.finished_at = now
        db.flush()
        difference = PaymentReconciliationDiscrepancy(
            payment_order_id=payment.order_id, evidence={"check_code": "unfreeze_status"}
        )
        assert PaymentRecoveryService(db)._normally_recoverable(difference)
        task = repository.recover(locked, now=now)
        assert task is not None and task.task_type == "unfreeze_submit"
        db.commit()
