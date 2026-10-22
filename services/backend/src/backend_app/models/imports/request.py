"""Persistent import facts. Transactions are owned by the calling service."""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    CHAR,
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    SmallInteger,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend_app.core.identifiers import new_id
from backend_app.db.base import Base
from backend_app.db.types import UTC_TIMESTAMP
from backend_app.models.admin import utc_now


class ImportRequest(Base):
    __tablename__ = "import_requests"
    __table_args__ = (
        UniqueConstraint(
            "property_company_id",
            "actor_scope",
            "actor_id",
            "request_scope",
            "idempotency_key",
            name="uq_import_request_identity",
        ),
        ForeignKeyConstraint(
            ["property_company_id"], ["property_companies.id"], name="fk_import_request_company"
        ),
        ForeignKeyConstraint(
            ["actor_scope", "actor_id"],
            ["admin_accounts.scope", "admin_accounts.id"],
            name="fk_import_request_actor",
        ),
        ForeignKeyConstraint(
            ["property_company_id", "batch_id"],
            ["import_batches.property_company_id", "import_batches.id"],
            name="fk_import_request_batch",
        ),
        CheckConstraint(
            "request_scope = 'create' OR request_scope IN ('source_file:' || "
            "batch_id::text,'precheck:' || batch_id::text,'confirm:' || "
            "batch_id::text,'cancel:' || batch_id::text,'retry_failed:' || "
            "batch_id::text,'error_file:' || batch_id::text,'recover:' || batch_id::text)",
            name="ck_import_request_scope",
        ),
        CheckConstraint(
            "jsonb_typeof(response_body) = 'object' AND "
            "((http_status = 201 AND request_scope IN "
            "('create','retry_failed:' || batch_id::text)) "
            "OR (http_status = 202 AND request_scope NOT IN "
            "('create','retry_failed:' || batch_id::text)))",
            name="ck_import_request_response",
        ),
        CheckConstraint(
            "request_fingerprint ~ '^[0-9a-f]{64}$' AND idempotency_key ~ '^[A-Za-z0-9_-]{1,128}$'",
            name="ck_import_request_digest",
        ),
        Index("ix_import_request_batch", "property_company_id", "batch_id", "created_at"),
        Index("ix_import_request_actor", "actor_scope", "actor_id"),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_id)
    property_company_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    actor_scope: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    request_scope: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    batch_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    http_status: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    response_body: Mapped[dict[str, Any]] = mapped_column(JSONB(none_as_null=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False, default=utc_now)
