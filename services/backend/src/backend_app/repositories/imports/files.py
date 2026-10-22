"""Database snapshots for bounded artifact generation and retention."""

from datetime import datetime

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from backend_app.models.imports import (
    ImportArtifact,
    ImportBatch,
    ImportBatchEvent,
    ImportIssue,
    ImportOperation,
    ImportRow,
    ImportTask,
)
from backend_app.repositories.imports.queries import visible_issue_filter


def generation_event(db: Session, batch_id: str, generation: int) -> ImportBatchEvent | None:
    return db.scalar(
        select(ImportBatchEvent).where(
            ImportBatchEvent.batch_id == batch_id,
            ImportBatchEvent.event_key == f"error-file:{generation}",
        )
    )


def error_rows(
    db: Session, batch: ImportBatch, next_row_no: int, limit: int = 500
) -> tuple[list[ImportRow], list[ImportIssue], int]:
    condition = and_(
        ImportRow.batch_id == batch.id,
        or_(
            ImportRow.error_count > 0,
            ImportRow.warning_count > 0,
            ImportRow.execution_status.in_(["failed", "uncertain"]),
        ),
    )
    rows = list(
        db.scalars(
            select(ImportRow)
            .where(condition, ImportRow.source_row_no >= next_row_no)
            .order_by(ImportRow.source_row_no)
            .limit(limit)
        )
    )
    issues = (
        list(
            db.scalars(
                select(ImportIssue)
                .where(visible_issue_filter(batch), ImportIssue.row_id.in_([r.id for r in rows]))
                .order_by(ImportIssue.id)
            )
        )
        if rows
        else []
    )
    total = int(db.scalar(select(func.count()).select_from(ImportRow).where(condition)) or 0)
    return rows, issues, total


def _protected_condition() -> ColumnElement[bool]:
    return or_(
        ImportBatch.uncertain_rows > 0,
        exists(
            select(ImportTask.id).where(
                ImportTask.batch_id == ImportBatch.id,
                ImportTask.status.in_(["ready", "running", "paused"]),
            )
        ),
        exists(
            select(ImportRow.id).where(
                ImportRow.batch_id == ImportBatch.id, ImportRow.execution_status == "uncertain"
            )
        ),
        exists(
            select(ImportRow.id)
            .join(ImportOperation, ImportRow.operation_id == ImportOperation.id)
            .where(
                ImportRow.batch_id == ImportBatch.id,
                ImportOperation.status.in_(["running", "uncertain"]),
            )
        ),
    )


def protected(db: Session, batch: ImportBatch) -> bool:
    return bool(db.scalar(select(_protected_condition()).where(ImportBatch.id == batch.id)))


def expired_batches(db: Session, now: datetime, limit: int = 10) -> list[ImportBatch]:
    return list(
        db.scalars(
            select(ImportBatch)
            .where(
                ImportBatch.retention_until <= now,
                ~_protected_condition(),
                or_(
                    exists(
                        select(ImportArtifact.id).where(
                            ImportArtifact.batch_id == ImportBatch.id,
                            ImportArtifact.deleted_at.is_(None),
                        )
                    ),
                    exists(
                        select(ImportRow.id).where(
                            ImportRow.batch_id == ImportBatch.id,
                            ImportRow.sensitive_cleared_at.is_(None),
                        )
                    ),
                ),
            )
            .order_by(ImportBatch.retention_until, ImportBatch.id)
            .limit(limit)
        )
    )


def expired_drafts(db: Session, deadline: datetime, limit: int = 20) -> list[ImportBatch]:
    return list(
        db.scalars(
            select(ImportBatch)
            .where(ImportBatch.status == "draft", ImportBatch.created_at <= deadline)
            .order_by(ImportBatch.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    )


def artifacts(db: Session, batch_id: str, limit: int = 100) -> list[ImportArtifact]:
    return list(
        db.scalars(
            select(ImportArtifact)
            .where(ImportArtifact.batch_id == batch_id, ImportArtifact.deleted_at.is_(None))
            .order_by(ImportArtifact.id)
            .limit(limit)
        )
    )


def has_artifacts(db: Session, batch_id: str) -> bool:
    return bool(
        db.scalar(
            select(
                exists(
                    select(ImportArtifact.id).where(
                        ImportArtifact.batch_id == batch_id, ImportArtifact.deleted_at.is_(None)
                    )
                )
            )
        )
    )


def clear_rows(db: Session, batch_id: str, now: datetime, limit: int = 500) -> None:
    rows = db.scalars(
        select(ImportRow)
        .where(ImportRow.batch_id == batch_id, ImportRow.sensitive_cleared_at.is_(None))
        .order_by(ImportRow.source_row_no)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    for row in rows:
        row.raw_values = None
        row.normalized_values = None
        row.sensitive_cleared_at = now


def clear_operations(db: Session, now: datetime, limit: int = 500) -> None:
    referenced = (
        select(ImportRow.id)
        .join(ImportBatch, ImportBatch.id == ImportRow.batch_id)
        .where(
            ImportRow.operation_id == ImportOperation.id,
            or_(
                ImportBatch.retention_until > now,
                ImportBatch.uncertain_rows > 0,
                ImportRow.execution_status == "uncertain",
                exists(
                    select(ImportTask.id).where(
                        ImportTask.batch_id == ImportBatch.id,
                        ImportTask.status.in_(["ready", "running", "paused"]),
                    )
                ),
            ),
        )
    )
    operations = db.scalars(
        select(ImportOperation)
        .where(
            ImportOperation.sensitive_cleared_at.is_(None),
            ImportOperation.status.not_in(["running", "uncertain"]),
            ~exists(referenced),
        )
        .order_by(ImportOperation.created_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    for operation in operations:
        operation.natural_key = None
        operation.sensitive_cleared_at = now
        operation.updated_at = now


def referenced_key(db: Session, key: str) -> bool:
    return bool(
        db.scalar(
            select(
                exists(
                    select(ImportArtifact.id).where(
                        ImportArtifact.storage_key == key, ImportArtifact.deleted_at.is_(None)
                    )
                )
            )
        )
    )
