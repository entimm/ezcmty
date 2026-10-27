"""Exercise the rollout switch and restoration using only isolated infrastructure."""

import hashlib
import shutil
import subprocess
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from tests.support.billing_services import BillingSetup
from tests.support.payment_orders import order_scenario
from tests.support.postgresql import temporary_database
from tests.support.wechatpay import sharing_response

from backend_app.core.errors import AppError
from backend_app.domain.payments.reconciliation import business_date
from backend_app.integrations.wechatpay.notifications import Notifications
from backend_app.integrations.wechatpay.payments import Payments
from backend_app.integrations.wechatpay.profit_sharing import ProfitSharing
from backend_app.integrations.wechatpay.statements import Statements
from backend_app.models.billing import Bill, BillSettlementEntry
from backend_app.models.payments import (
    BillPaymentReservation,
    PaymentOrder,
    PaymentReconciliationRun,
    PaymentUnfreezeOrder,
    ProfitSharingOrder,
    ProfitSharingRuleVersionItem,
)
from backend_app.repositories.payments.funds import FundsRepository
from backend_app.repositories.payments.reconciliation import ensure_run
from backend_app.repositories.payments.tasks import TaskLease, claim_tasks
from backend_app.schemas.payments.resident import (
    ResidentPaymentItemCreate,
    ResidentPaymentOrderCreate,
)
from backend_app.services.client.resident.payments import ResidentPaymentService
from backend_app.services.webhook.payments import PaymentWebhookService
from backend_app.services.worker.payments.notifications import NotificationService
from backend_app.services.worker.payments.orders import OrderService
from backend_app.services.worker.payments.profit_sharing import ProfitSharingService
from backend_app.services.worker.payments.reconciliation import ReconciliationService
from backend_app.services.worker.payments.unfreezing import UnfreezingService


def test_disabled_new_orders_preserve_full_old_payment_lifecycle_and_backup(
    billing_setup: BillingSetup, postgresql_url: str, tmp_path: Path
) -> None:
    case = order_scenario(billing_setup)
    settings = case.settings.model_copy(update={"payment_new_orders_enabled": False})
    now = case.now
    bill = billing_setup.create(month="2026-03", key="blocked_new_bill").bill
    with billing_setup.factory() as db:
        svc = ResidentPaymentService(db, settings)
        with pytest.raises(AppError) as error:
            svc.create(
                case.context,
                ResidentPaymentOrderCreate(
                    items=[
                        ResidentPaymentItemCreate(
                            bill_id=bill.id, expected_row_version=bill.row_version
                        )
                    ]
                ),
                "disabled_new_order",
            )
        assert error.value.code == "payment.configuration_unavailable"
        db.rollback()
        svc.request_recovery(case.context, case.payment.order_id)

    def claim(kind: str) -> TaskLease:
        with billing_setup.factory() as db:
            leases = claim_tasks(db, now=now, task_types={kind})
            assert len(leases) == 1
            db.commit()
            return leases[0]

    queried: list[str] = []

    def not_paid(request: httpx.Request) -> httpx.Response:
        queried.append(request.url.path)
        return case.peer.response(case.fact(status="NOTPAY"))

    client = case.peer.client(not_paid)
    OrderService(
        billing_setup.factory, settings, Payments(client), ProfitSharing(client), clock=lambda: now
    ).handle(case.lease("payment_query"))
    assert len(queried) == 1

    raw, headers = case.peer.notification(case.fact(), "transaction")
    with billing_setup.factory() as db:
        PaymentWebhookService(db, Notifications(client)).receive("payment", headers, raw)
    now += timedelta(seconds=1)
    NotificationService(
        billing_setup.factory, app_id=settings.wechat_miniapp_app_id, clock=lambda: now
    ).handle(claim("notification_process"))
    with billing_setup.factory() as db:
        payment = db.get(PaymentOrder, case.payment.order_id)
        assert payment is not None and payment.status == "succeeded"
        assert db.get(BillPaymentReservation, case.bill_id) is None
        assert db.scalar(select(func.count()).select_from(BillSettlementEntry)) == 1
        sharing = FundsRepository(db).sharing_orders(payment.id)[0]
        rule = db.get(ProfitSharingRuleVersionItem, case.payment.rule_item_ids[0])
        assert rule is not None
        fact = sharing_response()
        fact.update(out_order_no=sharing.order_no, transaction_id=payment.channel_transaction_no)
        fact["receivers"][0].update(account=rule.receiver_account, finish_time=now.isoformat())

    now += timedelta(minutes=2)
    channel = ProfitSharing(case.peer.client(lambda request: case.peer.response(fact)))
    ProfitSharingService(billing_setup.factory, channel, clock=lambda: now).handle(
        claim("profit_sharing_submit")
    )
    with billing_setup.factory() as db:
        unfreeze = db.scalar(select(PaymentUnfreezeOrder))
        assert unfreeze is not None
        fact = sharing_response()
        fact.update(out_order_no=unfreeze.order_no, transaction_id=payment.channel_transaction_no)
        fact["receivers"][0].update(account="1900000002", amount=9640, finish_time=now.isoformat())
    unfreezing = UnfreezingService(billing_setup.factory, channel, clock=lambda: now)
    unfreezing.handle(claim("unfreeze_submit"))
    now += timedelta(seconds=30)
    unfreezing.handle(claim("unfreeze_query"))
    with billing_setup.factory() as db:
        unfreeze = db.scalar(select(PaymentUnfreezeOrder))
        assert unfreeze is not None
        assert unfreeze.status == "succeeded" and unfreeze.unfrozen_cents == 9640
        payment = db.get(PaymentOrder, case.payment.order_id)
        assert payment is not None
        payer = case.fact()["payer"]["sp_openid"]
        content = (
            "交易时间,公众账号ID,商户号,特约商户号,商户订单号,微信订单号,"
            "交易状态,订单金额,手续费,货币种类,用户标识\n"
            f"{payment.paid_at.isoformat() if payment.paid_at else ''},wx_test_app,1900000001,"
            f"1900000002,{payment.order_no},{payment.channel_transaction_no},SUCCESS,100.00,"
            f"0.60,CNY,{payer}\n总交易单数,总交易额\n1,100.00\n"
        ).encode()
        run, _ = ensure_run(
            db,
            day=business_date(case.now),
            statement_type="trade",
            provider="1900000001",
            merchant="1900000002",
            now=now,
        )
        run_id = run.id
        db.commit()

    def statement(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v3/billdownload/file":
            return httpx.Response(200, content=content)
        if request.url.path.startswith("/v3/profitsharing/orders/"):
            return case.peer.response(fact)
        return case.peer.response(
            {
                "hash_type": "SHA1",
                "hash_value": hashlib.sha1(content, usedforsecurity=False).hexdigest(),
                "download_url": "https://api.mch.weixin.qq.com/v3/billdownload/file?token=isolated",
            }
        )

    ReconciliationService(
        billing_setup.factory,
        Statements(case.peer.client(statement)),
        service_provider_merchant_no="1900000001",
        app_id="wx_test_app",
        clock=lambda: now,
    ).handle(claim("reconciliation"))
    with billing_setup.factory() as db:
        completed_run = db.get(PaymentReconciliationRun, run_id)
        assert completed_run is not None and completed_run.status == "completed"
        assert completed_run.summary["discrepancy_count"] == 0
        source_url = str(db.connection().engine.url)

    # Back up this complete ledger and restore to another fresh test database.
    binaries = {name: shutil.which(name) for name in ("pg_dump", "pg_restore")}
    assert all(binaries.values()), "Release acceptance requires PostgreSQL backup tools"
    archive = tmp_path / "isolated-payment.dump"
    subprocess.run(
        [
            str(binaries["pg_dump"]),
            "--format=custom",
            "--no-owner",
            "--no-privileges",
            "--file",
            str(archive),
            source_url.replace("postgresql+psycopg:", "postgresql:"),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    with temporary_database(postgresql_url) as restored_url:
        subprocess.run(
            [
                str(binaries["pg_restore"]),
                "--exit-on-error",
                "--no-owner",
                "--no-privileges",
                "--dbname",
                restored_url.replace("postgresql+psycopg:", "postgresql:"),
                str(archive),
            ],
            check=True,
            capture_output=True,
            timeout=30,
        )
        engine = create_engine(restored_url)
        try:
            with Session(engine) as db:
                restored = db.get(PaymentOrder, case.payment.order_id)
                restored_bill = db.get(Bill, case.bill_id)
                assert restored is not None and restored.status == "succeeded"
                assert restored_bill is not None and restored_bill.outstanding_cents == 0
                assert db.scalar(select(func.count()).select_from(BillSettlementEntry)) == 1
                assert db.scalar(select(func.count()).select_from(ProfitSharingOrder)) == 1
                assert FundsRepository(db).remaining(restored.id) == {}
                restored_unfreeze = db.scalar(select(PaymentUnfreezeOrder))
                assert restored_unfreeze is not None and restored_unfreeze.unfrozen_cents == 9640
                with pytest.raises(IntegrityError):
                    db.execute(
                        text("UPDATE payment_orders SET status='unknown' WHERE id=:id"),
                        {"id": restored.id},
                    )
                    db.commit()
                db.rollback()
                assert db.get(BillPaymentReservation, case.bill_id) is None
        finally:
            engine.dispose()
