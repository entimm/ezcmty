from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from tests.support.billing_services import BillingSetup
from tests.support.payment_orders import OrderScenario, order_scenario, unused_channel

from backend_app.api.webhook.payments import get_notification_verifier
from backend_app.api.webhook.router import create_webhook_router
from backend_app.db.session import get_database_session
from backend_app.integrations.wechatpay.notifications import Notifications
from backend_app.models.admin import utc_now
from backend_app.models.billing import BillSettlementEntry
from backend_app.models.payments import (
    BillPaymentReservation,
    PaymentChannelNotification,
    PaymentOrder,
    PaymentTask,
)
from backend_app.repositories.payments.tasks import claim_tasks
from backend_app.services.worker.payments.notifications import NotificationService


def client_for(case: OrderScenario) -> TestClient:
    app = FastAPI()
    app.include_router(create_webhook_router())

    def database() -> Generator[Session]:
        with case.setup.factory() as db:
            yield db

    app.dependency_overrides[get_database_session] = database
    app.dependency_overrides[get_notification_verifier] = lambda: Notifications(
        case.peer.client(unused_channel)
    )
    return TestClient(app, raise_server_exceptions=False)


def test_valid_notification_ack_commits_only_evidence_and_task_then_posts_once(
    billing_setup: BillingSetup,
) -> None:
    case = order_scenario(billing_setup)
    raw, headers = case.peer.notification(case.fact(), "transaction")
    with client_for(case) as client:
        for _ in range(2):
            response = client.post(
                "/webhooks/payments/wechatpay/payment-success", content=raw, headers=headers
            )
            assert response.status_code == 204 and response.content == b""
    with billing_setup.factory() as db:
        assert db.scalar(select(func.count()).select_from(PaymentChannelNotification)) == 1
        assert (
            db.scalar(
                select(func.count())
                .select_from(PaymentTask)
                .where(PaymentTask.task_type == "notification_process")
            )
            == 1
        )
        assert db.scalar(select(func.count()).select_from(BillSettlementEntry)) == 0
        case.now = utc_now()
        lease = claim_tasks(db, now=case.now, task_types={"notification_process"})[0]
        db.commit()
    case.revoke()
    NotificationService(billing_setup.factory, app_id="wx_test_app", clock=lambda: case.now).handle(
        lease
    )
    with billing_setup.factory() as db:
        assert db.scalar(select(PaymentOrder.status)) == "succeeded"
        assert db.scalar(select(func.count()).select_from(BillSettlementEntry)) == 1
        assert db.get(BillPaymentReservation, case.bill_id) is None
        assert db.scalar(select(PaymentChannelNotification.status)) == "processed"


@pytest.mark.parametrize(
    "failure,status", [("signature", 401), ("format", 400), ("wrong_route", 400)]
)
def test_channel_failures_are_channel_ack_without_persistence(
    billing_setup: BillingSetup, failure: str, status: int
) -> None:
    case = order_scenario(billing_setup)
    raw, headers = case.peer.notification(case.fact(), "transaction")
    path = "/webhooks/payments/wechatpay/payment-success"
    if failure == "signature":
        headers.pop("Wechatpay-Signature")
    elif failure == "format":
        raw = b"{}"
        headers = case.peer.headers(raw)
    else:
        path = "/webhooks/payments/wechatpay/profit-sharing"
    with client_for(case) as client:
        response = client.post(path, content=raw, headers=headers)
        assert response.status_code == status
        assert response.json()["code"] == "FAIL"
        assert response.headers["content-type"] == "application/json"
        assert "type" not in response.json()
    with billing_setup.factory() as db:
        assert db.scalar(select(func.count()).select_from(PaymentChannelNotification)) == 0


def test_business_mismatch_is_persisted_then_quarantined_without_posting(
    billing_setup: BillingSetup,
) -> None:
    case = order_scenario(billing_setup)
    fact = case.fact()
    fact["amount"]["total"] = 9999
    raw, headers = case.peer.notification(fact, "transaction")
    with client_for(case) as client:
        assert (
            client.post(
                "/webhooks/payments/wechatpay/payment-success", content=raw, headers=headers
            ).status_code
            == 204
        )
    with billing_setup.factory() as db:
        case.now = utc_now()
        lease = claim_tasks(db, now=case.now, task_types={"notification_process"})[0]
        db.commit()
    NotificationService(billing_setup.factory, app_id="wx_test_app", clock=lambda: case.now).handle(
        lease
    )
    with billing_setup.factory() as db:
        assert db.scalar(select(PaymentChannelNotification.status)) == "quarantined"
        assert db.scalar(select(PaymentOrder.status)) == "pending"
        assert db.get(BillPaymentReservation, case.bill_id) is not None
        assert db.scalar(select(func.count()).select_from(BillSettlementEntry)) == 0


def test_save_failure_returns_500_and_keeps_no_partial_notification(
    billing_setup: BillingSetup, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = order_scenario(billing_setup)
    raw, headers = case.peer.notification(case.fact(), "transaction")

    def fail(*args: object, **kwargs: object) -> None:
        raise RuntimeError("private database diagnostic")

    monkeypatch.setattr("backend_app.services.webhook.payments.store_notification", fail)
    with client_for(case) as client:
        response = client.post(
            "/webhooks/payments/wechatpay/payment-success", content=raw, headers=headers
        )
        assert response.status_code == 500
        assert response.json() == {"code": "FAIL", "message": "通知暂未保存"}


def test_concurrent_duplicate_notices_share_one_processing_task(
    billing_setup: BillingSetup,
) -> None:
    case = order_scenario(billing_setup)
    raw, headers = case.peer.notification(case.fact(), "transaction")
    barrier = Barrier(2)

    def deliver(_: int) -> int:
        with client_for(case) as client:
            barrier.wait(timeout=5)
            return int(
                client.post(
                    "/webhooks/payments/wechatpay/payment-success", content=raw, headers=headers
                ).status_code
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(deliver, (1, 2))) == [204, 204]
    with billing_setup.factory() as db:
        assert db.scalar(select(func.count()).select_from(PaymentChannelNotification)) == 1
        assert (
            db.scalar(
                select(func.count())
                .select_from(PaymentTask)
                .where(PaymentTask.task_type == "notification_process")
            )
            == 1
        )
