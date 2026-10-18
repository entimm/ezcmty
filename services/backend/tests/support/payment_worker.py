"""Subprocess harness for the real runner; synthetic notices never represent funds success."""

import argparse
import os
import signal
from pathlib import Path
from threading import Event
from types import FrameType

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend_app.core.logging import configure_logging
from backend_app.models.admin import utc_now
from backend_app.models.payments import PaymentChannelNotification
from backend_app.repositories.payments.tasks import (
    TaskLease,
    complete_task,
    require_current_lease,
)
from backend_app.tasks.handlers.payments import PaymentHandlers
from backend_app.tasks.runner import run_worker


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("complete", "hold", "crash", "fail_once"))
    parser.add_argument("synchronization_directory", type=Path)
    args = parser.parse_args()
    directory: Path = args.synchronization_directory
    stop = Event()

    def stop_worker(signum: int, frame: FrameType | None) -> None:
        stop.set()
        (directory / "stop_received").touch()

    signal.signal(signal.SIGTERM, stop_worker)
    signal.signal(signal.SIGINT, stop_worker)
    configure_logging("INFO", "payment-worker-test")
    engine = create_engine(os.environ["APP_DATABASE_URL"])
    factory = sessionmaker(engine, expire_on_commit=False)
    dispatched = 0

    def handle_notice(lease: TaskLease) -> None:
        nonlocal dispatched
        dispatched += 1
        (directory / "entered").write_text(lease.id)
        if args.mode == "crash":
            os._exit(23)
        if args.mode == "fail_once" and dispatched == 1:
            raise RuntimeError("synthetic_handler_failure")
        if args.mode == "hold":
            # Parent explicitly releases the in-flight operation after signaling stop.
            released = Event()
            while not (directory / "release").exists():
                released.wait(0.02)
        with factory() as db:
            notice = db.scalars(
                select(PaymentChannelNotification)
                .where(PaymentChannelNotification.id == lease.target_id)
                .with_for_update()
            ).one()
            now = utc_now()
            require_current_lease(db, lease, now=now)
            notice.status = "ignored"
            notice.processed_at = now
            notice.updated_at = now
            complete_task(db, lease, now=now)
            db.commit()

    handlers = PaymentHandlers(tasks={"notification_process": handle_notice})
    try:
        run_worker(
            stop,
            factory=factory,
            handlers=handlers,
            poll_seconds=0.02,
            lease_seconds=3,
        )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
