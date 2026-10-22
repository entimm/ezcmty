from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend_app.models.imports import ImportBatch, ImportBatchEvent
from backend_app.repositories.pagination import read_page

SAFE_METADATA_KEYS = frozenset(
    {
        "format",
        "phase",
        "reason_code",
        "error_code",
        "attempt_count",
        "generation",
        "preview_version",
        "row_version",
        "total_rows",
        "processed_rows",
        "created_rows",
        "skipped_rows",
        "failed_rows",
        "uncertain_rows",
        "cancelled_rows",
        "progress_done",
        "progress_total",
        "byte_size",
    }
)


def append_event(
    db: Session,
    *,
    batch_id: str,
    event_key: str,
    event_type: str,
    now: datetime,
    from_status: str | None = None,
    to_status: str | None = None,
    actor_scope: str | None = None,
    actor_id: str | None = None,
    task_id: str | None = None,
    task_attempt: int | None = None,
    safe_metadata: dict[str, Any] | None = None,
) -> ImportBatchEvent:
    db.scalars(
        select(ImportBatch).where(ImportBatch.id == batch_id).with_for_update(of=ImportBatch)
    ).one()
    existing = db.scalar(
        select(ImportBatchEvent).where(
            ImportBatchEvent.batch_id == batch_id, ImportBatchEvent.event_key == event_key
        )
    )
    if existing is not None:
        return existing
    metadata = safe_metadata or {}
    if set(metadata) - SAFE_METADATA_KEYS or any(
        not isinstance(value, (str, int, bool, type(None))) for value in metadata.values()
    ):
        raise ValueError("Import event metadata must use safe scalar fields")
    sequence = (
        db.scalar(
            select(func.max(ImportBatchEvent.sequence_no)).where(
                ImportBatchEvent.batch_id == batch_id
            )
        )
        or 0
    ) + 1
    event = ImportBatchEvent(
        batch_id=batch_id,
        sequence_no=sequence,
        event_key=event_key,
        event_type=event_type,
        from_status=from_status,
        to_status=to_status,
        actor_scope=actor_scope,
        actor_id=actor_id,
        task_id=task_id,
        task_attempt=task_attempt,
        safe_metadata=metadata,
        created_at=now,
    )
    db.add(event)
    db.flush()
    return event


def page_events(
    db: Session, batch_id: str, *, page: int = 1, page_size: int = 20
) -> tuple[list[ImportBatchEvent], int]:
    return read_page(
        db,
        ImportBatchEvent,
        select(ImportBatchEvent).where(ImportBatchEvent.batch_id == batch_id),
        page=page,
        page_size=page_size,
        order=(("sequence_no", False),),
    )
