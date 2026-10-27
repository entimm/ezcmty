import json
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from threading import Barrier

import httpx
import pytest
from sqlalchemy import func, select
from tests.support.billing_services import BillingSetup
from tests.support.payment_orders import OrderScenario, order_scenario, unused_channel

from backend_app.core.errors import AppError
from backend_app.integrations.wechatpay.payments import Payments, parse_payment
from backend_app.integrations.wechatpay.profit_sharing import ProfitSharing
from backend_app.models.billing import BillSettlementEntry
from backend_app.models.payments import (
    BillPaymentReservation,
    PaymentChannelRequest,
    PaymentOrder,
    PaymentTask,
)
from backend_app.repositories.payments.channel_records import store_notification
from backend_app.repositories.payments.orders import OrdersRepository
from backend_app.repositories.payments.tasks import LeaseLost
from backend_app.schemas.payments.resident import (
    ResidentPaymentItemCreate,
    ResidentPaymentOrderCreate,
)
from backend_app.services.client.resident.payments import ResidentPaymentService
from backend_app.services.worker.payments.orders import OrderService


def worker(
    case: OrderScenario, handler: Callable[[httpx.Request], httpx.Response] = unused_channel
) -> OrderService:
    client = case.peer.client(handler)
    return OrderService(
        case.setup.factory,
        case.settings,
        Payments(client),
        ProfitSharing(client),
        clock=lambda: case.now,
    )


def test_create_is_atomic_full_balance_and_replay_survives_unbinding(
    billing_setup: BillingSetup,
) -> None:
    case = order_scenario(billing_setup)
    bill = billing_setup.create(month="2026-02", key="second", paid=3000).bill
    data = ResidentPaymentOrderCreate(
        items=[ResidentPaymentItemCreate(bill_id=bill.id, expected_row_version=bill.row_version)]
    )
    with billing_setup.factory() as db:
        result = ResidentPaymentService(db, case.settings).create(case.context, data, "new_order")
        assert result.amount_cents == 7000
        assert result.expires_at - result.created_at == timedelta(minutes=15)
        reservation = db.get(BillPaymentReservation, bill.id)
        assert reservation is not None and reservation.payment_order_id == result.id
        tasks = list(
            db.scalars(select(PaymentTask).where(PaymentTask.payment_order_id == result.id))
        )
        assert {task.task_type for task in tasks} == {"payment_submit", "payment_query"}
        assert "prepay_token" not in result.model_dump_json()
    case.revoke()
    with billing_setup.factory() as db:
        replay = ResidentPaymentService(db, case.settings).create(case.context, data, "new_order")
        assert replay.id == result.id and replay.available_actions == ["refresh", "close"]
        with pytest.raises(AppError, match="幂等键"):
            ResidentPaymentService(db, case.settings).create(
                case.context,
                ResidentPaymentOrderCreate(
                    items=[ResidentPaymentItemCreate(bill_id=case.bill_id, expected_row_version=1)]
                ),
                "new_order",
            )


@pytest.mark.parametrize(
    "version,error", [(99, "payment.bill_version_conflict"), (1, "payment.bill_reserved")]
)
def test_new_order_rejects_version_or_existing_reservation(
    billing_setup: BillingSetup, version: int, error: str
) -> None:
    case = order_scenario(billing_setup)
    with billing_setup.factory() as db:
        with pytest.raises(AppError) as caught:
            ResidentPaymentService(db, case.settings).create(
                case.context,
                ResidentPaymentOrderCreate(
                    items=[
                        ResidentPaymentItemCreate(
                            bill_id=case.bill_id, expected_row_version=version
                        )
                    ]
                ),
                "new",
            )
        assert caught.value.code == error
        assert db.scalar(select(func.count()).select_from(PaymentOrder)) == 1


def test_two_keys_compete_for_one_bill(billing_setup: BillingSetup) -> None:
    case = order_scenario(billing_setup)
    bill = billing_setup.create(month="2026-02", key="second").bill
    data = ResidentPaymentOrderCreate(
        items=[ResidentPaymentItemCreate(bill_id=bill.id, expected_row_version=bill.row_version)]
    )
    barrier = Barrier(2)

    def create(key: str) -> str:
        barrier.wait(timeout=5)
        with billing_setup.factory() as db:
            try:
                return ResidentPaymentService(db, case.settings).create(case.context, data, key).id
            except AppError as error:
                return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(create, ("one", "two")))
    assert results.count("payment.bill_reserved") == 1
    with billing_setup.factory() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(BillPaymentReservation)
                .where(BillPaymentReservation.bill_id == bill.id)
            )
            == 1
        )


def test_submit_has_durable_intent_no_transaction_and_original_parameters(
    billing_setup: BillingSetup,
) -> None:
    case = order_scenario(billing_setup)
    paths = []

    def handle(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        with billing_setup.factory() as db:
            active = db.scalar(
                select(func.count())
                .select_from(PaymentChannelRequest)
                .where(PaymentChannelRequest.outcome == "started")
            )
            assert active == 1
            # A conflicting guard can acquire all business locks during HTTP.
            order, authorized = OrdersRepository(db).guard_order(case.payment.order_id)
            assert authorized
            if request.method == "POST":
                body = json.loads(request.content)
                assert body["out_trade_no"] == order.order_no
                assert body["settle_info"]["profit_sharing"] is True
                assert order.status == "unknown"
                assert body["amount"]["total"] == 10000
        if request.method == "GET":
            return case.peer.response({"sub_mchid": "1900000002", "max_ratio": 3000})
        return case.peer.response({"prepay_id": "private-prepay-token"})

    worker(case, handle).handle(case.lease("payment_submit"))
    assert len(paths) == 2
    with billing_setup.factory() as db:
        service = ResidentPaymentService(
            db, case.settings, signer=Payments(case.peer.client(unused_channel))
        )
        detail = service.get(case.context, case.payment.order_id)
        assert detail.status == "payable" and "continue_payment" in detail.available_actions
        parameters = service.parameters(case.context, detail.id)
        assert parameters.client_parameters.package == "prepay_id=private-prepay-token"
    case.revoke()
    with billing_setup.factory() as db:
        with pytest.raises(AppError) as caught:
            ResidentPaymentService(db, case.settings).parameters(
                case.context, case.payment.order_id
            )
        assert caught.value.code == "resource.not_found"


def test_unknown_submit_preserves_reservation_then_queries_same_order(
    billing_setup: BillingSetup,
) -> None:
    case = order_scenario(billing_setup)

    def handle(request: httpx.Request) -> httpx.Response:
        if "merchant-configs" in request.url.path:
            return case.peer.response({"sub_mchid": "1900000002", "max_ratio": 3000})
        raise httpx.ReadTimeout("private diagnostic", request=request)

    worker(case, handle).submit(case.lease("payment_submit"))
    with billing_setup.factory() as db:
        assert db.get(BillPaymentReservation, case.bill_id) is not None
        assert (
            db.scalars(select(PaymentOrder).where(PaymentOrder.id == case.payment.order_id))
            .one()
            .status
            == "unknown"
        )
        assert (
            db.scalar(
                select(PaymentChannelRequest.error_code).where(
                    PaymentChannelRequest.operation == "payment_submit"
                )
            )
            == "TRANSPORT_UNKNOWN"
        )

    def queried(request: httpx.Request) -> httpx.Response:
        assert case.fact()["out_trade_no"] in request.url.path
        return case.peer.response(case.fact())

    worker(case, queried).query(case.lease("payment_query"))
    with billing_setup.factory() as db:
        assert (
            db.scalars(select(PaymentOrder).where(PaymentOrder.id == case.payment.order_id))
            .one()
            .status
            == "succeeded"
        )
        assert db.get(BillPaymentReservation, case.bill_id) is None
        assert db.scalar(select(func.count()).select_from(BillSettlementEntry)) == 1


def test_notpay_is_not_reliable_closure_and_authorization_scan_is_bounded(
    billing_setup: BillingSetup,
) -> None:
    case = order_scenario(billing_setup)
    worker(case, lambda _: case.peer.response(case.fact(status="NOTPAY"))).query(
        case.lease("payment_query")
    )
    with billing_setup.factory() as db:
        assert db.get(BillPaymentReservation, case.bill_id) is not None
        assert (
            db.scalars(select(PaymentOrder).where(PaymentOrder.id == case.payment.order_id))
            .one()
            .status
            == "pending"
        )
    case.revoke()
    assert worker(case).scan(limit=1) == 1
    with billing_setup.factory() as db:
        assert (
            db.scalars(select(PaymentOrder).where(PaymentOrder.id == case.payment.order_id))
            .one()
            .status
            == "closing"
        )
        assert db.get(BillPaymentReservation, case.bill_id) is not None
    worker(case).close(case.lease("payment_close"))
    with billing_setup.factory() as db:
        assert (
            db.scalars(select(PaymentOrder).where(PaymentOrder.id == case.payment.order_id))
            .one()
            .status
            == "closed"
        )
        assert db.get(BillPaymentReservation, case.bill_id) is None


def test_close_queries_first_and_verified_204_releases_only_original_reservation(
    billing_setup: BillingSetup,
) -> None:
    case = order_scenario(billing_setup)
    with billing_setup.factory() as db:
        db.add(
            PaymentChannelRequest(
                operation="payment_submit",
                payment_order_id=case.payment.order_id,
                request_snapshot={},
                outcome="transport_unknown",
                request_id="old",
                finished_at=case.now,
            )
        )
        db.commit()
    calls = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        if request.method == "GET":
            return case.peer.response(case.fact(status="NOTPAY"))
        return case.peer.response(None, 204)

    worker(case, handle).close(case.lease("payment_close"))
    assert calls == ["GET", "POST"]
    with billing_setup.factory() as db:
        assert (
            db.scalars(select(PaymentOrder).where(PaymentOrder.id == case.payment.order_id))
            .one()
            .status
            == "closed"
        )
        assert db.get(BillPaymentReservation, case.bill_id) is None


def test_late_success_is_saved_but_old_generation_cannot_apply(billing_setup: BillingSetup) -> None:
    case = order_scenario(billing_setup)
    lease = case.lease("payment_query")

    def handle(_: httpx.Request) -> httpx.Response:
        with billing_setup.factory() as db:
            task = db.get(PaymentTask, lease.id)
            assert task is not None
            task.attempt_count += 1
            db.commit()
        return case.peer.response(case.fact())

    with pytest.raises(LeaseLost):
        worker(case, handle).query(lease)
    with billing_setup.factory() as db:
        assert (
            db.scalars(select(PaymentOrder).where(PaymentOrder.id == case.payment.order_id))
            .one()
            .status
            == "pending"
        )
        detail = ResidentPaymentService(db, case.settings).get(case.context, case.payment.order_id)
        assert detail.confirmation_status == "awaiting_posting"
        assert "continue_payment" not in detail.available_actions
        assert (
            OrdersRepository(db).list_orders(
                user_id=case.context.user_id,
                app_id="wx_test_app",
                confirmation_status="awaiting_posting",
                page=50,
            )[1]
            == 1
        )
        assert (
            OrdersRepository(db).list_orders(
                user_id=case.context.user_id,
                app_id="wx_test_app",
                confirmation_status="unconfirmed",
            )[1]
            == 0
        )


def test_read_does_not_create_tasks_and_foreign_user_cannot_see_order(
    billing_setup: BillingSetup,
) -> None:
    case = order_scenario(billing_setup)
    with billing_setup.factory() as db:
        service = ResidentPaymentService(db, case.settings)
        before = db.scalar(select(func.count()).select_from(PaymentTask))
        service.get(case.context, case.payment.order_id)
        service.list(case.context, page=1, page_size=20)
        assert db.scalar(select(func.count()).select_from(PaymentTask)) == before
        with pytest.raises(AppError):
            service.get(
                replace(case.context, user_id="00000000-0000-4000-8000-000000000000"),
                case.payment.order_id,
            )


def test_close_consumes_durable_success_notice_without_channel_even_after_revocation(
    billing_setup: BillingSetup,
) -> None:
    case = order_scenario(billing_setup)
    with billing_setup.factory() as db:
        store_notification(
            db,
            channel_notification_id="paid",
            notification_type="payment_success",
            payload=parse_payment(case.fact()).snapshot(),
            now=case.now,
        )
        db.commit()
    case.revoke()
    worker(case).close(case.lease("payment_close"))
    with billing_setup.factory() as db:
        assert db.scalar(select(PaymentOrder.status)) == "succeeded"
        assert db.get(BillPaymentReservation, case.bill_id) is None
        assert db.scalar(select(func.count()).select_from(BillSettlementEntry)) == 1


def test_success_notice_during_channel_close_keeps_occupancy_until_posting(
    billing_setup: BillingSetup,
) -> None:
    case = order_scenario(billing_setup)
    with billing_setup.factory() as db:
        db.add(
            PaymentChannelRequest(
                operation="payment_submit",
                payment_order_id=case.payment.order_id,
                request_snapshot={},
                outcome="transport_unknown",
                request_id="old",
                finished_at=case.now,
            )
        )
        db.commit()

    def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return case.peer.response(case.fact(status="NOTPAY"))
        with billing_setup.factory() as db:
            store_notification(
                db,
                channel_notification_id="paid",
                notification_type="payment_success",
                payload=parse_payment(case.fact()).snapshot(),
                now=case.now,
            )
            db.commit()
        return case.peer.response(None, 204)

    worker(case, handle).close(case.lease("payment_close"))
    with billing_setup.factory() as db:
        assert db.scalar(select(PaymentOrder.status)) != "closed"
        assert db.get(BillPaymentReservation, case.bill_id) is not None
    worker(case).query(case.lease("payment_query"))
    with billing_setup.factory() as db:
        assert db.scalar(select(PaymentOrder.status)) == "succeeded"
        assert db.get(BillPaymentReservation, case.bill_id) is None


def test_authorization_revoked_during_ratio_check_prevents_submission(
    billing_setup: BillingSetup,
) -> None:
    case = order_scenario(billing_setup)

    def handle(request: httpx.Request) -> httpx.Response:
        assert "merchant-configs" in request.url.path
        case.revoke()
        return case.peer.response({"sub_mchid": "1900000002", "max_ratio": 3000})

    worker(case, handle).submit(case.lease("payment_submit"))
    with billing_setup.factory() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(PaymentChannelRequest)
                .where(PaymentChannelRequest.operation == "payment_submit")
            )
            == 0
        )
        assert db.get(BillPaymentReservation, case.bill_id) is not None
    worker(case).close(case.lease("payment_close"))
    with billing_setup.factory() as db:
        assert db.scalar(select(PaymentOrder.status)) == "closed"


def test_crashed_submission_is_queried_before_repeating_original_send(
    billing_setup: BillingSetup,
) -> None:
    case = order_scenario(billing_setup)
    with billing_setup.factory() as db:
        db.add(
            PaymentChannelRequest(
                operation="payment_submit",
                payment_order_id=case.payment.order_id,
                request_snapshot={},
                outcome="started",
                request_id="before_crash",
                created_at=case.now,
            )
        )
        db.commit()
    worker(case).submit(case.lease("payment_submit"))
    with billing_setup.factory() as db:
        assert db.scalar(select(func.count()).select_from(PaymentOrder)) == 1
        assert db.get(BillPaymentReservation, case.bill_id) is not None
        assert (
            db.scalar(select(PaymentTask.status).where(PaymentTask.task_type == "payment_query"))
            == "ready"
        )


def test_authenticated_not_found_retries_original_submission_before_expiry(
    billing_setup: BillingSetup,
) -> None:
    case = order_scenario(billing_setup)
    with billing_setup.factory() as db:
        db.add(
            PaymentChannelRequest(
                operation="payment_submit",
                payment_order_id=case.payment.order_id,
                request_snapshot={},
                outcome="transport_unknown",
                request_id="old",
                finished_at=case.now,
                created_at=case.now - timedelta(seconds=1),
            )
        )
        db.commit()
    worker(
        case,
        lambda _: case.peer.response({"code": "ORDER_NOT_EXIST", "message": "订单不存在"}, 404),
    ).query(case.lease("payment_query"))
    calls = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        if request.method == "GET":
            return case.peer.response({"sub_mchid": "1900000002", "max_ratio": 3000})
        original = case.fact()["out_trade_no"]
        assert json.loads(request.content)["out_trade_no"] == original
        return case.peer.response({"prepay_id": "recovered-original-token"})

    worker(case, handle).submit(case.lease("payment_submit"))
    assert calls == ["GET", "POST"]
    with billing_setup.factory() as db:
        assert db.scalar(select(func.count()).select_from(PaymentOrder)) == 1
        assert db.scalar(select(PaymentOrder.status)) == "payable"
