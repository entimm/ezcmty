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


class ImportIssue(Base):
    __tablename__ = "import_issues"
    __table_args__ = (
        ForeignKeyConstraint(["batch_id"], ["import_batches.id"], name="fk_import_issue_batch"),
        ForeignKeyConstraint(
            ["batch_id", "row_id"],
            ["import_rows.batch_id", "import_rows.id"],
            name="fk_import_issue_row",
        ),
        UniqueConstraint(
            "batch_id",
            "row_id",
            "preview_version",
            "phase",
            "code",
            "field_key",
            "column_name",
            "column_index",
            "cell_reference",
            name="uq_import_issue_identity",
            postgresql_nulls_not_distinct=True,
        ),
        CheckConstraint(
            "(phase = 'parse' AND preview_version = 0) OR (phase IN ('precheck','apply') "
            "AND preview_version > 0)",
            name="ck_import_issue_phase",
        ),
        CheckConstraint("severity IN ('warning','error')", name="ck_import_issue_severity"),
        CheckConstraint(
            "column_index IS NULL OR column_index > 0", name="ck_import_issue_location"
        ),
        CheckConstraint(
            "detail IS NULL OR jsonb_typeof(detail) = 'object'", name="ck_import_issue_detail"
        ),
        Index("ix_import_issue_preview", "batch_id", "preview_version", "severity", "row_id"),
        Index("ix_import_issue_code", "batch_id", "code", "id"),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_id)
    batch_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    row_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    preview_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    phase: Mapped[str] = mapped_column(String(16), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    code: Mapped[str] = mapped_column(String(128), nullable=False)
    field_key: Mapped[str | None] = mapped_column(String(64))
    column_name: Mapped[str | None] = mapped_column(String(128))
    column_index: Mapped[int | None] = mapped_column(Integer)
    cell_reference: Mapped[str | None] = mapped_column(String(32))
    message: Mapped[str] = mapped_column(String(1000), nullable=False)
    suggestion: Mapped[str | None] = mapped_column(String(1000))
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    created_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False, default=utc_now)
