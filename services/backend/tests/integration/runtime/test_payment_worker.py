import os
import subprocess
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from threading import Event
from time import monotonic

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from tests.support.paths import BACKEND_ROOT
from tests.support.payment_tasks import notification_task
from tests.support.postgresql import stop_service

from backend_app.models.admin import utc_now
from backend_app.models.payments import PaymentChannelNotification, PaymentOrder, PaymentTask

pytestmark = pytest.mark.slow


@pytest.fixture
def factory(migrated_database_url: str) -> Iterator[sessionmaker[Session]]:
    engine = create_engine(migrated_database_url)
    try:
        yield sessionmaker(engine, expire_on_commit=False)
    finally:
        engine.dispose()


def eventually(predicate: Callable[[], bool], *, seconds: float = 10) -> None:
    deadline = monotonic() + seconds
    interval = Event()
    while monotonic() < deadline:
        if predicate():
            return
        interval.wait(0.02)
    raise AssertionError("Payment worker condition timed out")


@contextmanager
def worker(
    directory: Path, database_url: str, *, mode: str = "complete"
) -> Iterator[tuple[subprocess.Popen[bytes], Path]]:
    directory.mkdir()
    log_path = directory / "worker.log"
    # Only this test's explicitly provisioned database is passed to the harness.
    environment = {**os.environ, "APP_DATABASE_URL": database_url}
    with log_path.open("wb") as log:
        process = subprocess.Popen(
            [sys.executable, "-m", "tests.support.payment_worker", mode, str(directory)],
            cwd=BACKEND_ROOT,
            env=environment,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            yield process, log_path
        finally:
            stop_service(process)


def task_state(factory: sessionmaker[Session], task_id: str) -> tuple[str, int]:
    with factory() as db:
        task = db.get(PaymentTask, task_id)
        assert task is not None
        return task.status, task.attempt_count


def test_worker_drains_inflight_task_then_stops_without_claiming_next(
    factory: sessionmaker[Session], migrated_database_url: str, tmp_path: Path
) -> None:
    now = utc_now()
    first = notification_task(factory, now=now - timedelta(seconds=2), key="first")
    second = notification_task(factory, now=now - timedelta(seconds=1), key="second")
    directory = tmp_path / "graceful"
    with worker(directory, migrated_database_url, mode="hold") as (process, log):
        eventually(lambda: (directory / "entered").exists())
        assert "worker_ready scheduler=running task_handlers=1" in log.read_text()
        assert task_state(factory, first) == ("running", 1)
        with factory() as db:
            original_expiry = db.scalars(
                select(PaymentTask.lease_expires_at).where(PaymentTask.id == first)
            ).one()
        assert original_expiry is not None

        def heartbeat_renewed() -> bool:
            with factory() as db:
                current = db.scalars(
                    select(PaymentTask.lease_expires_at).where(PaymentTask.id == first)
                ).one()
                return current is not None and current > original_expiry

        eventually(heartbeat_renewed)
        process.terminate()
        eventually(lambda: (directory / "stop_received").exists())
        assert process.poll() is None
        (directory / "release").touch()
        assert process.wait(timeout=10) == 0
        assert "worker_stopped" in log.read_text()
    assert task_state(factory, first) == ("completed", 1)
    assert task_state(factory, second) == ("ready", 0)


def test_handler_failure_preserves_task_and_worker_processes_other_work(
    factory: sessionmaker[Session], migrated_database_url: str, tmp_path: Path
) -> None:
    now = utc_now()
    failed = notification_task(factory, now=now - timedelta(seconds=2), key="failed")
    next_task = notification_task(factory, now=now - timedelta(seconds=1), key="next")
    with worker(tmp_path / "failure", migrated_database_url, mode="fail_once") as (process, log):
        eventually(lambda: task_state(factory, next_task) == ("completed", 1))
        assert process.poll() is None
        assert task_state(factory, failed) == ("running", 1)
        with factory() as db:
            failed_task = db.get(PaymentTask, failed)
            assert failed_task is not None
            notice = db.get(PaymentChannelNotification, failed_task.notification_id)
            assert notice is not None and notice.status == "pending"
        assert "payment.task_handler_failed" in log.read_text()
        process.terminate()
        assert process.wait(timeout=10) == 0


def test_abnormal_exit_restarts_from_expired_persistent_lease(
    factory: sessionmaker[Session], migrated_database_url: str, tmp_path: Path
) -> None:
    task_id = notification_task(factory, now=utc_now(), key="restart")
    with worker(tmp_path / "crash", migrated_database_url, mode="crash") as (process, log):
        assert process.wait(timeout=10) == 23
        assert "worker_ready scheduler=running task_handlers=1" in log.read_text()
        assert "worker_stopped" not in log.read_text()
    assert task_state(factory, task_id) == ("running", 1)
    with worker(tmp_path / "restart", migrated_database_url) as (process, log):
        eventually(lambda: task_state(factory, task_id) == ("completed", 2))
        assert process.poll() is None
        process.terminate()
        assert process.wait(timeout=10) == 0
        assert "worker_stopped" in log.read_text()
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(PaymentOrder)) == 0
        notice = db.scalars(select(PaymentChannelNotification)).one()
        assert notice.status == "ignored"
        assert notice.processed_at is not None


def test_worker_does_not_report_ready_when_task_storage_is_unavailable(
    database_url: str, tmp_path: Path
) -> None:
    with worker(tmp_path / "unready", database_url) as (process, log):
        assert process.wait(timeout=10) != 0
        assert "worker_ready" not in log.read_text()
