"""Persistent import facts. Transactions are owned by the calling service."""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend_app.core.identifiers import new_id
from backend_app.db.base import Base
from backend_app.db.types import UTC_TIMESTAMP
from backend_app.models.admin import utc_now


class ImportRow(Base):
    __tablename__ = "import_rows"
    __table_args__ = (
        ForeignKeyConstraint(["batch_id"], ["import_batches.id"], name="fk_import_row_batch"),
        ForeignKeyConstraint(
            ["operation_id"], ["import_operations.id"], name="fk_import_row_operation"
        ),
        UniqueConstraint("batch_id", "source_row_no", name="uq_import_row_number"),
        UniqueConstraint("batch_id", "id", name="uq_import_row_batch_id"),
        CheckConstraint(
            "source_row_no > 0 AND warning_count >= 0 AND error_count >= 0 "
            "AND validation_version >= 0",
            name="ck_import_row_source",
        ),
        CheckConstraint(
            "(raw_values IS NULL) = (sensitive_cleared_at IS NOT NULL) AND "
            "(sensitive_cleared_at IS NULL OR normalized_values IS NULL) AND (raw_values "
            "IS NULL OR jsonb_typeof(raw_values) = 'object') AND (normalized_values IS "
            "NULL OR jsonb_typeof(normalized_values) = 'object')",
            name="ck_import_row_values",
        ),
        CheckConstraint(
            "validation_status IN ('staged','valid','invalid') AND planned_action IN "
            "('create','update','skip','conflict','none')",
            name="ck_import_row_validation",
        ),
        CheckConstraint(
            "execution_status IN "
            "('pending','created','skipped','failed','uncertain','cancelled','excluded') "
            "AND ((execution_status = 'pending') = (result_at IS NULL)) AND "
            "(execution_status NOT IN ('created','skipped','failed','uncertain') OR "
            "operation_id IS NOT NULL)",
            name="ck_import_row_execution",
        ),
        Index("ix_import_row_validation", "batch_id", "validation_status", "source_row_no"),
        Index("ix_import_row_execution", "batch_id", "execution_status", "source_row_no"),
        Index("ix_import_row_operation", "operation_id"),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_id)
    batch_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    source_row_no: Mapped[int] = mapped_column(BigInteger, nullable=False)
    raw_values: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    normalized_values: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    validation_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="staged", server_default="staged"
    )
    planned_action: Mapped[str] = mapped_column(
        String(16), nullable=False, default="none", server_default="none"
    )
    operation_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    warning_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    validation_version: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    execution_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending"
    )
    result_at: Mapped[datetime | None] = mapped_column(UTC_TIMESTAMP)
    sensitive_cleared_at: Mapped[datetime | None] = mapped_column(UTC_TIMESTAMP)
    created_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False, default=utc_now)
