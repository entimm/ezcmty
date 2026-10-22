from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend_app.models.payments import PaymentTask
from backend_app.repositories.payments.tasks import LeaseLost, TaskLease, claim_tasks, renew_task
from backend_app.tasks.handlers.payments import PaymentHandlers
from backend_app.tasks.types import SourceLeaseLost, TaskEnvelope


class PaymentTaskSource:
    name = "payment"

    def __init__(self, handlers: PaymentHandlers) -> None:
        self.handlers = handlers
        self.task_count = len(handlers.tasks)
        self.periodic_checks = handlers.periodic_checks

    def probe(self, db: Session) -> None:
        db.execute(select(PaymentTask.id).limit(1))

    def claim(self, db: Session, *, now: datetime, lease_seconds: int) -> tuple[TaskEnvelope, ...]:
        leases = claim_tasks(
            db, now=now, task_types=self.handlers.tasks.keys(), limit=1, lease_seconds=lease_seconds
        )
        return tuple(
            TaskEnvelope(
                lease.id,
                lease.task_type,
                lease.target_id,
                lease.attempt_count,
                lease.lease_expires_at,
            )
            for lease in leases
        )

    def renew(self, db: Session, lease: TaskEnvelope, *, now: datetime, lease_seconds: int) -> None:
        try:
            renew_task(db, self._lease(lease), now=now, lease_seconds=lease_seconds)
        except LeaseLost as error:
            raise SourceLeaseLost from error

    def dispatch(self, lease: TaskEnvelope) -> None:
        try:
            self.handlers.dispatch(self._lease(lease))
        except LeaseLost as error:
            raise SourceLeaseLost from error

    def close(self) -> None:
        pass

    @staticmethod
    def _lease(lease: TaskEnvelope) -> TaskLease:
        return TaskLease(
            lease.id, lease.task_type, lease.target_id, lease.attempt_count, lease.lease_expires_at
        )
