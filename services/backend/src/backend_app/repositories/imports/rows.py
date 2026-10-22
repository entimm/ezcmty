from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from backend_app.core.identifiers import new_id
from backend_app.models.imports import ImportRow
from backend_app.repositories.pagination import read_page


def stage_rows(
    db: Session, batch_id: str, values: list[tuple[int, dict[str, Any]]], *, now: datetime
) -> None:
    if not values:
        return
    db.execute(
        insert(ImportRow)
        .values(
            [
                {
                    "id": new_id(),
                    "batch_id": batch_id,
                    "source_row_no": row_no,
                    "raw_values": raw,
                    "validation_status": "staged",
                    "planned_action": "none",
                    "execution_status": "pending",
                    "validation_version": 0,
                    "warning_count": 0,
                    "error_count": 0,
                    "created_at": now,
                    "updated_at": now,
                }
                for row_no, raw in values
            ]
        )
        .on_conflict_do_nothing(constraint="uq_import_row_number")
    )


def read_rows(
    db: Session, batch_id: str, *, next_row_no: int = 1, limit: int = 200, lock: bool = False
) -> list[ImportRow]:
    query = (
        select(ImportRow)
        .where(ImportRow.batch_id == batch_id, ImportRow.source_row_no >= next_row_no)
        .order_by(ImportRow.source_row_no)
        .limit(limit)
    )
    if lock:
        query = query.with_for_update(of=ImportRow)
    return list(db.scalars(query))


def page_rows(
    db: Session,
    batch_id: str,
    *,
    page: int = 1,
    page_size: int = 20,
    validation_status: str | None = None,
    execution_status: str | None = None,
    planned_action: str | None = None,
) -> tuple[list[ImportRow], int]:
    query = select(ImportRow).where(ImportRow.batch_id == batch_id)
    for name, value in (
        ("validation_status", validation_status),
        ("execution_status", execution_status),
        ("planned_action", planned_action),
    ):
        if value is not None:
            query = query.where(getattr(ImportRow, name) == value)
    return read_page(
        db, ImportRow, query, page=page, page_size=page_size, order=(("source_row_no", False),)
    )
