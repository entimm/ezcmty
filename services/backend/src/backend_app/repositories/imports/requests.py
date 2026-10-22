from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend_app.models.imports import ImportRequest


class IdempotencyConflict(Exception):
    def __init__(self) -> None:
        super().__init__("Import request key was used with different input")


def find_request(
    db: Session,
    *,
    property_company_id: str,
    actor_scope: str,
    actor_id: str,
    request_scope: str,
    idempotency_key: str,
    request_fingerprint: str | None = None,
) -> ImportRequest | None:
    record = db.scalar(
        select(ImportRequest).where(
            ImportRequest.property_company_id == property_company_id,
            ImportRequest.actor_scope == actor_scope,
            ImportRequest.actor_id == actor_id,
            ImportRequest.request_scope == request_scope,
            ImportRequest.idempotency_key == idempotency_key,
        )
    )
    if (
        record is not None
        and request_fingerprint is not None
        and record.request_fingerprint != request_fingerprint
    ):
        raise IdempotencyConflict
    return record


def record_request(
    db: Session,
    *,
    property_company_id: str,
    actor_scope: str,
    actor_id: str,
    request_scope: str,
    idempotency_key: str,
    request_fingerprint: str,
    batch_id: str,
    http_status: int,
    response_body: dict[str, Any],
    now: datetime,
) -> ImportRequest:
    record = ImportRequest(
        property_company_id=property_company_id,
        actor_scope=actor_scope,
        actor_id=actor_id,
        request_scope=request_scope,
        idempotency_key=idempotency_key,
        request_fingerprint=request_fingerprint,
        batch_id=batch_id,
        http_status=http_status,
        response_body=response_body,
        created_at=now,
    )
    db.add(record)
    db.flush()
    return record
