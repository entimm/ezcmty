import logging
from collections.abc import Callable
from datetime import datetime
from threading import Event, Thread
from time import monotonic

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from backend_app.core.logging import log_exception
from backend_app.models.admin import utc_now
from backend_app.models.payments import PaymentTask
from backend_app.repositories.payments.tasks import LeaseLost, TaskLease, claim_tasks, renew_task
from backend_app.tasks.handlers.payments import PaymentHandlers


class LeaseHeartbeat:
    def __init__(
        self,
        factory: sessionmaker[Session],
        lease: TaskLease,
        *,
        lease_seconds: int,
        clock: Callable[[], datetime],
    ) -> None:
        self.factory = factory
        self.lease = lease
        self.lease_seconds = lease_seconds
        self.clock = clock
        self.stop = Event()
        self.thread = Thread(target=self._run, name="payment-lease-heartbeat", daemon=True)

    def _run(self) -> None:
        while not self.stop.wait(self.lease_seconds / 3):
            try:
                with self.factory() as db:
                    renew_task(db, self.lease, now=self.clock(), lease_seconds=self.lease_seconds)
                    db.commit()
            except LeaseLost:
                return
            except Exception as error:
                log_exception(error, code="payment.task_lease_renewal_failed")
                return

    def start(self) -> None:
        self.thread.start()

    def close(self) -> None:
        self.stop.set()
        self.thread.join(timeout=15)
        if self.thread.is_alive():
            raise RuntimeError("Payment lease heartbeat did not stop")


def run_worker(
    stop_event: Event,
    *,
    factory: sessionmaker[Session],
    handlers: PaymentHandlers,
    poll_seconds: float = 0.5,
    periodic_seconds: float = 30,
    lease_seconds: int = 30,
    clock: Callable[[], datetime] = utc_now,
) -> None:
    """Own task claim/heartbeat only. Business use cases choose retry and transaction outcomes."""
    if poll_seconds <= 0 or periodic_seconds <= 0 or not 3 <= lease_seconds <= 3600:
        raise ValueError("Invalid worker scheduling bounds")
    logger = logging.getLogger(__name__)
    with factory() as db:
        db.execute(select(PaymentTask.id).limit(1))
        db.rollback()
    next_periodic = 0.0
    logger.info("worker_ready scheduler=running task_handlers=%d", len(handlers.tasks))
    try:
        while not stop_event.is_set():
            if monotonic() >= next_periodic:
                for check in handlers.periodic_checks.values():
                    if stop_event.is_set():
                        break
                    try:
                        check()
                    except Exception as error:
                        log_exception(error, code="payment.periodic_check_failed")
                next_periodic = monotonic() + periodic_seconds
            if stop_event.is_set():
                break
            with factory() as db:
                leases = claim_tasks(
                    db,
                    now=clock(),
                    task_types=handlers.tasks.keys(),
                    lease_seconds=lease_seconds,
                )
                db.commit()
            if not leases:
                stop_event.wait(poll_seconds)
                continue
            for lease in leases:
                heartbeat = LeaseHeartbeat(factory, lease, lease_seconds=lease_seconds, clock=clock)
                heartbeat.start()
                try:
                    handlers.dispatch(lease)
                except LeaseLost:
                    logger.info("payment_task_lease_lost")
                except Exception as error:
                    # Preserve the lease for takeover; the runner cannot choose a funds outcome.
                    log_exception(error, code="payment.task_handler_failed")
                finally:
                    heartbeat.close()
    finally:
        logger.info("worker_stopped")
