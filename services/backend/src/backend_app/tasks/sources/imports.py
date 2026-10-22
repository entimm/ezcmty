from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend_app.models.imports import ImportTask
from backend_app.repositories.imports.tasks import LeaseLost, TaskLease, claim_tasks, renew_task
from backend_app.tasks.handlers.imports import IMPORT_TASK_PHASES, ImportHandlers
from backend_app.tasks.types import SourceLeaseLost, TaskEnvelope


class ImportTaskSource:
    name = "import"

    def __init__(self, handlers: ImportHandlers) -> None:
        self.handlers = handlers
        self.task_count = len(handlers.tasks)
        self.periodic_checks = handlers.periodic_checks

    def probe(self, db: Session) -> None:
        db.execute(select(ImportTask.id).limit(1))

    def claim(self, db: Session, *, now: datetime, lease_seconds: int) -> tuple[TaskEnvelope, ...]:
        leases = claim_tasks(
            db,
            now=now,
            phases=tuple(IMPORT_TASK_PHASES[key] for key in self.handlers.tasks),
            limit=1,
            lease_seconds=lease_seconds,
        )
        reverse = {phase: key for key, phase in IMPORT_TASK_PHASES.items()}
        return tuple(
            TaskEnvelope(
                lease.id,
                reverse[lease.phase],
                lease.batch_id,
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
        if self.handlers.on_close is not None:
            self.handlers.on_close()

    @staticmethod
    def _lease(lease: TaskEnvelope) -> TaskLease:
        return TaskLease(
            lease.id,
            IMPORT_TASK_PHASES[lease.task_type],
            lease.target_id,
            lease.attempt_count,
            lease.lease_expires_at,
        )
