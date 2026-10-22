from sqlalchemy import select
from sqlalchemy.orm import Session

from backend_app.models.imports import ImportBatch
from backend_app.repositories.pagination import read_page


def get_batch(
    db: Session,
    batch_id: str,
    *,
    property_company_id: str | None = None,
    actor_scope: str | None = None,
    lock: bool = False,
) -> ImportBatch | None:
    query = select(ImportBatch).where(ImportBatch.id == batch_id)
    if property_company_id is not None:
        query = query.where(ImportBatch.property_company_id == property_company_id)
    if actor_scope is not None:
        query = query.where(ImportBatch.created_by_scope == actor_scope)
    if lock:
        query = query.with_for_update(of=ImportBatch)
    return db.scalar(query)


def page_batches(
    db: Session,
    *,
    property_company_id: str | None = None,
    actor_scope: str | None = None,
    community_id: str | None = None,
    status: str | None = None,
    template_key: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[ImportBatch], int]:
    query = select(ImportBatch)
    for name, value in (
        ("property_company_id", property_company_id),
        ("created_by_scope", actor_scope),
        ("community_id", community_id),
        ("status", status),
        ("template_key", template_key),
    ):
        if value is not None:
            query = query.where(getattr(ImportBatch, name) == value)
    return read_page(
        db,
        ImportBatch,
        query,
        page=page,
        page_size=page_size,
        order=(("created_at", True), ("id", True)),
    )
