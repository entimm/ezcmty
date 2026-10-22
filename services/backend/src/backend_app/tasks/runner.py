import logging
from collections.abc import Callable, Sequence
from datetime import datetime
from threading import Event, Thread
from time import monotonic

from sqlalchemy.orm import Session, sessionmaker

from backend_app.core.logging import log_exception
from backend_app.models.admin import utc_now
from backend_app.tasks.handlers.payments import PaymentHandlers
from backend_app.tasks.sources.payments import PaymentTaskSource
from backend_app.tasks.types import SourceLeaseLost, TaskEnvelope, TaskSource


class LeaseHeartbeat:
    def __init__(
        self,
        factory: sessionmaker[Session],
        lease: TaskEnvelope,
        *,
        source: TaskSource,
        lease_seconds: int,
        clock: Callable[[], datetime],
    ) -> None:
        self.factory = factory
        self.lease = lease
        self.source = source
        self.lease_seconds = lease_seconds
        self.clock = clock
        self.stop = Event()
        self.thread = Thread(target=self._run, name=f"{source.name}-lease-heartbeat", daemon=True)

    def _run(self) -> None:
        while not self.stop.wait(self.lease_seconds / 3):
            try:
                # Never share a Session with the handler thread.
                with self.factory() as db:
                    self.source.renew(
                        db, self.lease, now=self.clock(), lease_seconds=self.lease_seconds
                    )
                    db.commit()
            except SourceLeaseLost:
                return
            except Exception as error:
                log_exception(error, code=f"{self.source.name}.task_lease_renewal_failed")
                return

    def start(self) -> None:
        self.thread.start()

    def close(self) -> None:
        self.stop.set()
        self.thread.join(timeout=15)
        if self.thread.is_alive():
            raise RuntimeError("Task lease heartbeat did not stop")


def run_worker(
    stop_event: Event,
    *,
    factory: sessionmaker[Session],
    handlers: PaymentHandlers | None = None,
    sources: Sequence[TaskSource] | None = None,
    poll_seconds: float = 0.5,
    periodic_seconds: float = 30,
    lease_seconds: int = 30,
    clock: Callable[[], datetime] = utc_now,
) -> None:
    """One claim per source per round; use cases own bounded work, outcomes and transactions."""
    if poll_seconds <= 0 or periodic_seconds <= 0 or not 3 <= lease_seconds <= 3600:
        raise ValueError("Invalid worker scheduling bounds")
    if sources is not None and handlers is not None:
        raise ValueError("Supply task sources or legacy payment handlers")
    selected: tuple[TaskSource, ...]
    if sources is not None:
        selected = tuple(sources)
    elif handlers is not None:
        selected = (PaymentTaskSource(handlers),)
    else:
        selected = ()
    if not selected or len({source.name for source in selected}) != len(selected):
        raise ValueError("Worker requires distinct task sources")
    logger = logging.getLogger(__name__)
    with factory() as db:
        for source in selected:
            source.probe(db)
        db.rollback()
    next_periodic = 0.0
    payment_count = next((s.task_count for s in selected if s.name == "payment"), 0)
    logger.info(
        "worker_ready scheduler=running task_handlers=%d task_sources=%d total_handlers=%d",
        payment_count,
        len(selected),
        sum(source.task_count for source in selected),
    )
    try:
        while not stop_event.is_set():
            if monotonic() >= next_periodic:
                for source in selected:
                    for check in source.periodic_checks.values():
                        if stop_event.is_set():
                            break
                        try:
                            check()
                        except Exception as error:
                            log_exception(error, code=f"{source.name}.periodic_check_failed")
                next_periodic = monotonic() + periodic_seconds
            claimed = False
            for source in selected:
                if stop_event.is_set():
                    break
                with factory() as db:
                    leases = source.claim(db, now=clock(), lease_seconds=lease_seconds)
                    db.commit()
                claimed = claimed or bool(leases)
                for lease in leases:
                    heartbeat = LeaseHeartbeat(
                        factory, lease, source=source, lease_seconds=lease_seconds, clock=clock
                    )
                    heartbeat.start()
                    try:
                        source.dispatch(lease)
                    except SourceLeaseLost:
                        logger.info("%s_task_lease_lost", source.name)
                    except Exception as error:
                        # Preserve durable lease for takeover; choose no business outcome.
                        log_exception(error, code=f"{source.name}.task_handler_failed")
                    finally:
                        heartbeat.close()
            if not claimed and not stop_event.is_set():
                stop_event.wait(poll_seconds)
    finally:
        for source in selected:
            source.close()
        logger.info("worker_stopped")
