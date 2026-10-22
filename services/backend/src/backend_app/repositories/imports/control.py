"""Import transaction primitives. These never commit the caller's transaction."""

from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend_app.domain.imports.checkpoint import validate_checkpoint
from backend_app.models.imports import (
    ImportBatch,
    ImportRow,
    ImportTask,
)


def task(
    db: Session, batch: ImportBatch, phase: str, checkpoint: dict[str, Any], now: datetime
) -> ImportTask:
    validate_checkpoint(phase, checkpoint)
    item = db.scalar(
        select(ImportTask)
        .where(ImportTask.batch_id == batch.id, ImportTask.phase == phase)
        .with_for_update()
    )
    if item is None:
        item = ImportTask(
            batch_id=batch.id,
            phase=phase,
            checkpoint=checkpoint,
            next_run_at=now,
            created_at=now,
            updated_at=now,
        )
        db.add(item)
    else:
        item.checkpoint = checkpoint
        item.status = "ready"
        item.lease_expires_at = None
        item.completed_at = None
        item.last_error_code = None
        item.progress_done = 0
        item.progress_total = 0
        item.next_run_at = now
        item.updated_at = now
    db.flush()
    return item


def event(
    db: Session,
    batch: ImportBatch,
    key: str,
    event_type: str,
    now: datetime,
    *,
    actor_scope: str | None = None,
    actor_id: str | None = None,
    task_id: str | None = None,
    task_attempt: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    from backend_app.repositories.imports.events import append_event

    append_event(
        db,
        batch_id=batch.id,
        event_key=key,
        event_type=event_type,
        now=now,
        to_status=batch.status,
        actor_scope=actor_scope,
        actor_id=actor_id,
        task_id=task_id,
        task_attempt=task_attempt,
        safe_metadata=metadata,
    )


def recalculate(db: Session, batch: ImportBatch) -> None:
    db.flush()
    rows = db.execute(
        select(ImportRow.execution_status, func.count())
        .where(ImportRow.batch_id == batch.id)
        .group_by(ImportRow.execution_status)
    ).all()
    counts = dict(rows)
    batch.total_rows = sum(counts.values())
    for state, attr in [
        ("created", "created_rows"),
        ("skipped", "skipped_rows"),
        ("failed", "failed_rows"),
        ("uncertain", "uncertain_rows"),
        ("cancelled", "cancelled_rows"),
    ]:
        setattr(batch, attr, counts.get(state, 0))
    batch.processed_rows = batch.total_rows - counts.get("pending", 0) - counts.get("uncertain", 0)
    batch.planned_create_rows = int(
        db.scalar(
            select(func.count())
            .select_from(ImportRow)
            .where(ImportRow.batch_id == batch.id, ImportRow.planned_action == "create")
        )
        or 0
    )
    batch.planned_skip_rows = int(
        db.scalar(
            select(func.count())
            .select_from(ImportRow)
            .where(ImportRow.batch_id == batch.id, ImportRow.planned_action == "skip")
        )
        or 0
    )
    batch.warning_rows = int(
        db.scalar(
            select(func.count())
            .select_from(ImportRow)
            .where(ImportRow.batch_id == batch.id, ImportRow.warning_count > 0)
        )
        or 0
    )
    batch.error_rows = int(
        db.scalar(
            select(func.count())
            .select_from(ImportRow)
            .where(ImportRow.batch_id == batch.id, ImportRow.error_count > 0)
        )
        or 0
    )


def exclude_rows(
    db: Session, batch: ImportBatch, include_warning_rows: bool, now: datetime
) -> None:
    from sqlalchemy import or_, update

    condition = or_(
        ImportRow.validation_status != "valid",
        ImportRow.operation_id.is_(None),
        ImportRow.planned_action.not_in(["create", "skip"]),
    )
    if not include_warning_rows:
        condition = or_(condition, ImportRow.warning_count > 0)
    db.execute(
        update(ImportRow)
        .where(ImportRow.batch_id == batch.id, ImportRow.execution_status == "pending", condition)
        .values(execution_status="excluded", result_at=now, updated_at=now)
    )


def cancel_remaining(db: Session, batch: ImportBatch, now: datetime) -> None:
    from sqlalchemy import update

    db.execute(
        update(ImportRow)
        .where(ImportRow.batch_id == batch.id, ImportRow.execution_status == "pending")
        .values(execution_status="cancelled", result_at=now, updated_at=now)
    )
    db.execute(
        update(ImportTask)
        .where(ImportTask.batch_id == batch.id, ImportTask.status.in_(["ready", "paused"]))
        .values(status="cancelled", lease_expires_at=None, completed_at=now, updated_at=now)
    )
    recalculate(db, batch)
    batch.status = "cancelled"
    batch.finished_at = now
    batch.updated_at = now
