from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from backend_app.core.identifiers import new_id
from backend_app.models.imports import ImportOperation


def get_operation(db: Session, operation_id: str, *, lock: bool = False) -> ImportOperation | None:
    query = select(ImportOperation).where(ImportOperation.id == operation_id)
    if lock:
        query = query.with_for_update(of=ImportOperation)
    return db.scalar(query)


def ensure_operation(
    db: Session,
    *,
    property_company_id: str,
    operation_key: str,
    operation_type: str,
    natural_key: dict[str, Any],
    input_fingerprint: str,
    now: datetime,
) -> ImportOperation:
    db.execute(
        insert(ImportOperation)
        .values(
            id=new_id(),
            property_company_id=property_company_id,
            operation_key=operation_key,
            operation_type=operation_type,
            natural_key=natural_key,
            input_fingerprint=input_fingerprint,
            status="ready",
            attempt_count=0,
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_nothing(constraint="uq_import_operation_key")
    )
    operation = db.scalars(
        select(ImportOperation)
        .where(
            ImportOperation.property_company_id == property_company_id,
            ImportOperation.operation_key == operation_key,
        )
        .with_for_update(of=ImportOperation)
    ).one()
    if (
        operation.operation_type != operation_type
        or operation.input_fingerprint != input_fingerprint
    ):
        raise ValueError("Import operation input identity mismatch")
    return operation
