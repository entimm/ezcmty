import re
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from backend_app.core.identifiers import new_id
from backend_app.domain.imports.checkpoint import validate_checkpoint
from backend_app.models.imports import ImportBatch, ImportTask
from backend_app.repositories.imports.events import append_event


class LeaseLost(Exception):
    def __init__(self) -> None:
        super().__init__("Import task lease is no longer current")


@dataclass(frozen=True)
class TaskLease:
    id: str
    phase: str
    batch_id: str
    attempt_count: int
    lease_expires_at: datetime


def ensure_task(
    db: Session,
    phase: str,
    batch_id: str,
    *,
    checkpoint: dict[str, Any],
    now: datetime,
    next_run_at: datetime | None = None,
    reactivate: bool = False,
) -> ImportTask:
    validated = validate_checkpoint(phase, checkpoint)
    due = next_run_at or now
    db.execute(
        insert(ImportTask)
        .values(
            id=new_id(),
            phase=phase,
            batch_id=batch_id,
            status="ready",
            next_run_at=due,
            attempt_count=0,
            progress_done=0,
            progress_total=0,
            checkpoint=validated,
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_nothing(constraint="uq_import_task_phase")
    )
    task = db.scalars(
        select(ImportTask)
        .where(ImportTask.batch_id == batch_id, ImportTask.phase == phase)
        .with_for_update(of=ImportTask)
    ).one()
    if task.status == "ready":
        task.next_run_at = min(task.next_run_at, due)
        task.updated_at = now
    elif reactivate and task.status in {"completed", "paused", "cancelled"}:
        task.status = "ready"
        task.next_run_at = due
        task.checkpoint = validated
        task.progress_done = 0
        task.progress_total = 0
        task.completed_at = None
        task.last_error_code = None
        task.updated_at = now
    db.flush()
    return task


def claim_tasks(
    db: Session,
    *,
    now: datetime,
    phases: Collection[str] = ("parse", "precheck", "apply", "artifact"),
    limit: int = 1,
    lease_seconds: int = 30,
) -> tuple[TaskLease, ...]:
    if not 1 <= limit <= 100 or not 3 <= lease_seconds <= 3600:
        raise ValueError("Invalid import task claim bounds")
    eligible = and_(
        ImportTask.phase.in_(phases),
        or_(
            and_(ImportTask.status == "ready", ImportTask.next_run_at <= now),
            and_(ImportTask.status == "running", ImportTask.lease_expires_at <= now),
        ),
    )
    # Every worker/control-plane path coordinates batch before task. Claim events need
    # that same batch lock; never hold a task lock while waiting for a batch owner.
    candidate_ids = tuple(
        db.scalars(
            select(ImportTask.id)
            .join(ImportBatch, ImportBatch.id == ImportTask.batch_id)
            .where(eligible)
            .order_by(ImportTask.next_run_at, ImportTask.id)
            .limit(limit)
            .with_for_update(of=ImportBatch, skip_locked=True)
        )
    )
    if not candidate_ids:
        return ()
    rows = db.scalars(
        select(ImportTask)
        .where(ImportTask.id.in_(candidate_ids), eligible)
        .order_by(ImportTask.next_run_at, ImportTask.id)
        .with_for_update(of=ImportTask, skip_locked=True)
    ).all()
    leases: list[TaskLease] = []
    expires_at = now + timedelta(seconds=lease_seconds)
    for task in rows:
        takeover = task.status == "running"
        task.status = "running"
        task.attempt_count += 1
        task.lease_expires_at = expires_at
        task.updated_at = now
        task.started_at = task.started_at or now
        append_event(
            db,
            batch_id=task.batch_id,
            event_key=f"task-claim:{task.id}:{task.attempt_count}",
            event_type="task_taken_over" if takeover else "task_claimed",
            now=now,
            task_id=task.id,
            task_attempt=task.attempt_count,
            safe_metadata={"phase": task.phase, "attempt_count": task.attempt_count},
        )
        leases.append(
            TaskLease(
                task.id,
                task.phase,
                task.batch_id,
                task.attempt_count,
                expires_at,
            )
        )
    db.flush()
    return tuple(leases)


def require_current_lease(db: Session, lease: TaskLease, *, now: datetime) -> ImportTask:
    """Call after acquiring business locks; retain this lock through business result commit."""
    task = db.scalar(
        select(ImportTask)
        .where(
            ImportTask.id == lease.id,
            ImportTask.attempt_count == lease.attempt_count,
            ImportTask.status == "running",
            ImportTask.lease_expires_at > now,
        )
        .with_for_update(of=ImportTask)
    )
    if task is None:
        raise LeaseLost
    return task


def _change(db: Session, lease: TaskLease, *, now: datetime, values: dict[str, Any]) -> None:
    changed = db.scalar(
        update(ImportTask)
        .where(
            ImportTask.id == lease.id,
            ImportTask.attempt_count == lease.attempt_count,
            ImportTask.status == "running",
            ImportTask.lease_expires_at > now,
        )
        .values(**values, updated_at=now)
        .returning(ImportTask.id)
    )
    if changed is None:
        raise LeaseLost


def renew_task(db: Session, lease: TaskLease, *, now: datetime, lease_seconds: int = 30) -> None:
    if not 3 <= lease_seconds <= 3600:
        raise ValueError("Invalid import task lease interval")
    _change(db, lease, now=now, values={"lease_expires_at": now + timedelta(seconds=lease_seconds)})


def complete_task(db: Session, lease: TaskLease, *, now: datetime) -> None:
    _change(
        db,
        lease,
        now=now,
        values={
            "status": "completed",
            "lease_expires_at": None,
            "last_error_code": None,
            "completed_at": now,
        },
    )


def _error_code(code: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", code):
        raise ValueError("Task diagnostics must use a bounded error code")
    return code


def reschedule_task(
    db: Session,
    lease: TaskLease,
    *,
    now: datetime,
    next_run_at: datetime,
    error_code: str | None = None,
) -> None:
    _change(
        db,
        lease,
        now=now,
        values={
            "status": "ready",
            "lease_expires_at": None,
            "next_run_at": next_run_at,
            "last_error_code": _error_code(error_code) if error_code else None,
        },
    )


def pause_task(db: Session, lease: TaskLease, *, now: datetime, error_code: str) -> None:
    _change(
        db,
        lease,
        now=now,
        values={
            "status": "paused",
            "lease_expires_at": None,
            "last_error_code": _error_code(error_code),
        },
    )


def advance_checkpoint(
    db: Session,
    lease: TaskLease,
    *,
    now: datetime,
    checkpoint: dict[str, Any],
    progress_done: int,
    progress_total: int,
) -> None:
    if not 0 <= progress_done <= progress_total:
        raise ValueError("Invalid import progress")
    _change(
        db,
        lease,
        now=now,
        values={
            "checkpoint": validate_checkpoint(lease.phase, checkpoint),
            "progress_done": progress_done,
            "progress_total": progress_total,
        },
    )


def cancel_task(db: Session, lease: TaskLease, *, now: datetime) -> None:
    _change(
        db,
        lease,
        now=now,
        values={"status": "cancelled", "lease_expires_at": None, "completed_at": now},
    )
