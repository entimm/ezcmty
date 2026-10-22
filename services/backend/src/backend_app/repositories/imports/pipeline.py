"""Bounded stage reads and writes; no business decisions or transaction commits."""

from collections.abc import Iterator
from datetime import datetime
from typing import Any

from sqlalchemy import func, select, tuple_, update
from sqlalchemy.orm import Session

from backend_app.models.imports import ImportOperation, ImportRow


def validated_count(db: Session, batch_id: str, version: int) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(ImportRow)
            .where(ImportRow.batch_id == batch_id, ImportRow.validation_version == version)
        )
        or 0
    )


def duplicate_natural_key_rows(
    db: Session, batch_id: str, *, chunk_size: int
) -> Iterator[ImportRow]:
    duplicates = (
        select(ImportOperation.operation_type, ImportOperation.natural_key)
        .join(ImportRow, ImportRow.operation_id == ImportOperation.id)
        .where(ImportRow.batch_id == batch_id)
        .group_by(ImportOperation.operation_type, ImportOperation.natural_key)
        .having(func.count() > 1)
    )
    return iter(
        db.scalars(
            select(ImportRow)
            .join(ImportOperation, ImportOperation.id == ImportRow.operation_id)
            .where(
                ImportRow.batch_id == batch_id,
                tuple_(ImportOperation.operation_type, ImportOperation.natural_key).in_(duplicates),
            )
            .execution_options(yield_per=chunk_size)
        )
    )


def preview_facts(db: Session, batch_id: str, *, chunk_size: int) -> Iterator[list[Any]]:
    facts = db.execute(
        select(
            ImportRow.id,
            ImportRow.source_row_no,
            ImportRow.normalized_values,
            ImportRow.validation_status,
            ImportRow.planned_action,
            ImportRow.warning_count,
            ImportRow.error_count,
            ImportRow.operation_id,
        )
        .where(ImportRow.batch_id == batch_id)
        .order_by(ImportRow.source_row_no)
        .execution_options(yield_per=chunk_size)
    )
    return (list(fact) for fact in facts)


def next_pending_row(db: Session, batch_id: str, next_row_no: int) -> ImportRow | None:
    return db.scalar(
        select(ImportRow)
        .where(
            ImportRow.batch_id == batch_id,
            ImportRow.source_row_no >= next_row_no,
            ImportRow.execution_status.in_(["pending", "uncertain"]),
        )
        .order_by(ImportRow.source_row_no)
        .limit(1)
        .with_for_update(of=ImportRow)
    )


def row_by_id(db: Session, row_id: str) -> ImportRow | None:
    return db.get(ImportRow, row_id)


def cancel_pending_rows(db: Session, batch_id: str, *, now: datetime) -> None:
    db.execute(
        update(ImportRow)
        .where(ImportRow.batch_id == batch_id, ImportRow.execution_status == "pending")
        .values(execution_status="cancelled", result_at=now, updated_at=now)
    )
