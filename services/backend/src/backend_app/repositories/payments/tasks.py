import re
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from backend_app.core.identifiers import new_id
from backend_app.models.payments import PaymentTask

TASK_TARGETS = {
    "payment_submit": "payment_order_id",
    "payment_query": "payment_order_id",
    "payment_close": "payment_order_id",
    "profit_sharing_submit": "profit_sharing_order_id",
    "profit_sharing_query": "profit_sharing_order_id",
    "unfreeze_submit": "unfreeze_order_id",
    "unfreeze_query": "unfreeze_order_id",
    "notification_process": "notification_id",
    "reconciliation": "reconciliation_run_id",
}


class LeaseLost(Exception):
    def __init__(self) -> None:
        super().__init__("Payment task lease is no longer current")


@dataclass(frozen=True)
class TaskLease:
    id: str
    task_type: str
    target_id: str
    attempt_count: int
    lease_expires_at: datetime


def ensure_task(
    db: Session,
    task_type: str,
    target_id: str,
    *,
    now: datetime,
    next_run_at: datetime | None = None,
    reactivate: bool = False,
) -> PaymentTask:
    """Merge by the declared target. Running work is never reset or given a new generation."""
    target_name = TASK_TARGETS[task_type]
    target = getattr(PaymentTask, target_name)
    due = next_run_at or now
    db.execute(
        insert(PaymentTask)
        .values(
            id=new_id(),
            task_type=task_type,
            **{target_name: target_id},
            status="ready",
            next_run_at=due,
            attempt_count=0,
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_nothing(
            index_elements=[PaymentTask.task_type, target], index_where=target.is_not(None)
        )
    )
    task = db.scalars(
        select(PaymentTask)
        .where(PaymentTask.task_type == task_type, target == target_id)
        .with_for_update(of=PaymentTask)
    ).one()
    if task.status == "ready":
        task.next_run_at = min(task.next_run_at, due)
        task.updated_at = now
    elif reactivate and task.status in {"completed", "paused"}:
        task.status = "ready"
        task.next_run_at = due
        task.last_error = None
        task.updated_at = now
    db.flush()
    return task


def claim_tasks(
    db: Session,
    *,
    now: datetime,
    task_types: Collection[str],
    limit: int = 1,
    lease_seconds: int = 30,
) -> tuple[TaskLease, ...]:
    if not 1 <= limit <= 100 or not 3 <= lease_seconds <= 3600:
        raise ValueError("Invalid payment task claim bounds")
    rows = db.scalars(
        select(PaymentTask)
        .where(
            PaymentTask.task_type.in_(task_types),
            or_(
                and_(PaymentTask.status == "ready", PaymentTask.next_run_at <= now),
                and_(PaymentTask.status == "running", PaymentTask.lease_expires_at <= now),
            ),
        )
        .order_by(PaymentTask.next_run_at, PaymentTask.id)
        .limit(limit)
        .with_for_update(of=PaymentTask, skip_locked=True)
    ).all()
    leases: list[TaskLease] = []
    expires_at = now + timedelta(seconds=lease_seconds)
    for task in rows:
        task.status = "running"
        task.attempt_count += 1
        task.lease_expires_at = expires_at
        task.updated_at = now
        leases.append(
            TaskLease(
                task.id,
                task.task_type,
                getattr(task, TASK_TARGETS[task.task_type]),
                task.attempt_count,
                expires_at,
            )
        )
    db.flush()
    return tuple(leases)


def require_current_lease(db: Session, lease: TaskLease, *, now: datetime) -> PaymentTask:
    """Call after acquiring business locks; retain this lock through business result commit."""
    task = db.scalar(
        select(PaymentTask)
        .where(
            PaymentTask.id == lease.id,
            PaymentTask.attempt_count == lease.attempt_count,
            PaymentTask.status == "running",
            PaymentTask.lease_expires_at > now,
        )
        .with_for_update(of=PaymentTask)
    )
    if task is None:
        raise LeaseLost
    return task


def _change(db: Session, lease: TaskLease, *, now: datetime, values: dict[str, Any]) -> None:
    changed = db.scalar(
        update(PaymentTask)
        .where(
            PaymentTask.id == lease.id,
            PaymentTask.attempt_count == lease.attempt_count,
            PaymentTask.status == "running",
            PaymentTask.lease_expires_at > now,
        )
        .values(**values, updated_at=now)
        .returning(PaymentTask.id)
    )
    if changed is None:
        raise LeaseLost


def renew_task(db: Session, lease: TaskLease, *, now: datetime, lease_seconds: int = 30) -> None:
    if not 3 <= lease_seconds <= 3600:
        raise ValueError("Invalid payment task lease interval")
    _change(db, lease, now=now, values={"lease_expires_at": now + timedelta(seconds=lease_seconds)})


def complete_task(db: Session, lease: TaskLease, *, now: datetime) -> None:
    _change(
        db,
        lease,
        now=now,
        values={"status": "completed", "lease_expires_at": None, "last_error": None},
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
            "last_error": _error_code(error_code) if error_code else None,
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
            "last_error": _error_code(error_code),
        },
    )
