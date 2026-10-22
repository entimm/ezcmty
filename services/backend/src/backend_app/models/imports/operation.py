"""Persistent import facts. Transactions are owned by the calling service."""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    CHAR,
    BigInteger,
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend_app.core.identifiers import new_id
from backend_app.db.base import Base
from backend_app.db.types import UTC_TIMESTAMP
from backend_app.models.admin import utc_now


class ImportOperation(Base):
    __tablename__ = "import_operations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["property_company_id"], ["property_companies.id"], name="fk_import_operation_company"
        ),
        UniqueConstraint("property_company_id", "operation_key", name="uq_import_operation_key"),
        CheckConstraint(
            "operation_key ~ '^[0-9a-f]{64}$' AND input_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_import_operation_identity",
        ),
        CheckConstraint(
            "(natural_key IS NULL) = (sensitive_cleared_at IS NOT NULL) AND (natural_key "
            "IS NULL OR jsonb_typeof(natural_key) = 'object')",
            name="ck_import_operation_natural_key",
        ),
        CheckConstraint(
            "status IN ('ready','running','succeeded','skipped','failed','uncertain') "
            "AND (status NOT IN ('succeeded','skipped','failed','uncertain') OR "
            "processed_at IS NOT NULL)",
            name="ck_import_operation_status",
        ),
        CheckConstraint(
            "(target_type IS NULL) = (target_id IS NULL)", name="ck_import_operation_target"
        ),
        CheckConstraint("attempt_count >= 0", name="ck_import_operation_attempts"),
        Index("ix_import_operation_company_status", "property_company_id", "status", "id"),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_id)
    property_company_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    operation_key: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    operation_type: Mapped[str] = mapped_column(String(64), nullable=False)
    natural_key: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    input_fingerprint: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="ready", server_default="ready"
    )
    target_type: Mapped[str | None] = mapped_column(String(64))
    target_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    attempt_count: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    last_attempt_at: Mapped[datetime | None] = mapped_column(UTC_TIMESTAMP)
    processed_at: Mapped[datetime | None] = mapped_column(UTC_TIMESTAMP)
    sensitive_cleared_at: Mapped[datetime | None] = mapped_column(UTC_TIMESTAMP)
    created_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False, default=utc_now)
