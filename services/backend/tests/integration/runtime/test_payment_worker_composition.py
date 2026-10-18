import os
import signal
import subprocess
import sys
from pathlib import Path
from threading import Event
from time import monotonic

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from tests.support.paths import BACKEND_ROOT
from tests.support.payment_tasks import notification_task
from tests.support.postgresql import stop_service

from backend_app.core.config import get_settings
from backend_app.models.admin import utc_now
from backend_app.models.payments import PaymentChannelNotification, PaymentTask
from backend_app.repositories.payments.tasks import TASK_TARGETS
from backend_app.runtimes.worker import build_handlers


def test_production_worker_registers_all_business_handlers_without_merchant_secrets(
    migrated_database_url: str,
) -> None:
    engine = create_engine(migrated_database_url)
    try:
        handlers = build_handlers(sessionmaker(engine), get_settings())
        assert set(handlers.tasks) == TASK_TARGETS.keys()
        assert set(handlers.periodic_checks) == {"payment_authorizations", "daily_reconciliation"}
    finally:
        engine.dispose()


def test_production_entrypoint_consumes_durable_notice_and_stops_without_merchant_secrets(
    migrated_database_url: str, tmp_path: Path
) -> None:
    engine = create_engine(migrated_database_url)
    factory = sessionmaker(engine)
    task_id = notification_task(factory, now=utc_now())
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("APP_WECHATPAY_")
    }
    environment.update(
        APP_DATABASE_URL=migrated_database_url,
        APP_REDIS_URL="redis://127.0.0.1:1/0",
        APP_PAYMENT_NEW_ORDERS_ENABLED="false",
        APP_WECHAT_MINIAPP_APP_ID="",
    )
    output = tmp_path / "production-worker.log"
    try:
        with output.open("wb") as log:
            process = subprocess.Popen(
                [sys.executable, "-m", "backend_app.runtimes.worker"],
                cwd=BACKEND_ROOT,
                env=environment,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            try:
                deadline = monotonic() + 15
                interval = Event()
                while monotonic() < deadline:
                    assert process.poll() is None, output.read_text()
                    with factory() as db:
                        status = db.scalar(
                            select(PaymentTask.status).where(PaymentTask.id == task_id)
                        )
                    if status == "completed":
                        break
                    interval.wait(0.05)
                else:
                    raise AssertionError(output.read_text())
                assert "worker_ready scheduler=running task_handlers=9" in output.read_text()
                with factory() as db:
                    assert db.scalar(select(PaymentChannelNotification.status)) == "quarantined"
                process.send_signal(signal.SIGTERM)
                assert process.wait(timeout=10) == 0
                assert "worker_stopped" in output.read_text()
            finally:
                stop_service(process)
    finally:
        engine.dispose()
