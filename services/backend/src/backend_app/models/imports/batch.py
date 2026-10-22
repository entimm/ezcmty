"""Persistent import facts. Transactions are owned by the calling service."""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    CHAR,
    BigInteger,
    Boolean,
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


class ImportBatch(Base):
    __tablename__ = "import_batches"
    __table_args__ = (
        UniqueConstraint("property_company_id", "id", name="uq_import_batch_company_id"),
        ForeignKeyConstraint(
            ["property_company_id"], ["property_companies.id"], name="fk_import_batch_company"
        ),
        ForeignKeyConstraint(
            ["property_company_id", "community_id"],
            ["communities.property_company_id", "communities.id"],
            name="fk_import_batch_community",
        ),
        ForeignKeyConstraint(
            ["property_company_id", "parent_batch_id"],
            ["import_batches.property_company_id", "import_batches.id"],
            name="fk_import_batch_parent",
        ),
        ForeignKeyConstraint(
            ["created_by_scope", "created_by_id"],
            ["admin_accounts.scope", "admin_accounts.id"],
            name="fk_import_batch_creator",
        ),
        CheckConstraint(
            "(scope_type = 'company' AND community_id IS NULL) OR (scope_type = "
            "'community' AND community_id IS NOT NULL)",
            name="ck_import_batch_scope",
        ),
        CheckConstraint("mode = 'create' AND template_version_no > 0", name="ck_import_batch_mode"),
        CheckConstraint("jsonb_typeof(scope_snapshot) = 'object'", name="ck_import_batch_json"),
        CheckConstraint(
            "template_config_hash ~ '^[0-9a-f]{64}$' AND (preview_fingerprint IS NULL OR "
            "preview_fingerprint ~ '^[0-9a-f]{64}$')",
            name="ck_import_batch_digests",
        ),
        CheckConstraint(
            "status IN "
            "('draft','uploading','prechecking','preview_ready','executing','completed','"
            "partial_failed','failed','blocked','cancel_requested','cancelled','expired')",
            name="ck_import_batch_status",
        ),
        CheckConstraint(
            "(confirmed_at IS NULL AND apply_policy IS NULL AND include_warning_rows IS "
            "NULL) OR (confirmed_at IS NOT NULL AND apply_policy IS NOT NULL AND apply_policy IN "
            "('all_rows','valid_rows_only') AND include_warning_rows IS NOT NULL)",
            name="ck_import_batch_confirmation",
        ),
        CheckConstraint(
            "(preview_version = 0 AND preview_fingerprint IS NULL AND preview_expires_at "
            "IS NULL) OR (preview_version > 0 AND preview_fingerprint IS NOT NULL AND "
            "preview_expires_at IS NOT NULL)",
            name="ck_import_batch_preview",
        ),
        CheckConstraint(
            "total_rows >= 0 AND planned_create_rows >= 0 AND planned_update_rows >= 0 "
            "AND planned_skip_rows >= 0 AND warning_rows >= 0 AND error_rows >= 0 AND "
            "created_rows >= 0 AND updated_rows >= 0 AND skipped_rows >= 0 AND "
            "failed_rows >= 0 AND uncertain_rows >= 0 AND cancelled_rows >= 0 AND "
            "processed_rows >= 0 AND preview_version >= 0 AND row_version > 0 AND "
            "processed_rows <= total_rows AND planned_update_rows = 0 AND updated_rows = "
            "0",
            name="ck_import_batch_statistics",
        ),
        CheckConstraint(
            "((status IN ('completed','partial_failed','failed','cancelled','expired')) "
            "= (finished_at IS NOT NULL)) AND (uncertain_rows = 0 OR status NOT IN "
            "('completed','partial_failed','failed','cancelled','expired'))",
            name="ck_import_batch_finished",
        ),
        Index("ix_import_batch_company_time", "property_company_id", "created_at", "id"),
        Index(
            "ix_import_batch_scope_status",
            "property_company_id",
            "community_id",
            "status",
            "created_at",
            "id",
        ),
        Index(
            "ix_import_batch_template",
            "template_key",
            "template_version_no",
            "template_config_hash",
        ),
        Index("ix_import_batch_parent", "property_company_id", "parent_batch_id"),
        Index("ix_import_batch_creator", "created_by_scope", "created_by_id"),
        Index("ix_import_batch_retention", "retention_until", "id"),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_id)
    property_company_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    community_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    scope_type: Mapped[str] = mapped_column(String(16), nullable=False)
    scope_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB(none_as_null=True), nullable=False)
    template_key: Mapped[str] = mapped_column(String(64), nullable=False)
    template_version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    template_config_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    mode: Mapped[str] = mapped_column(
        String(16), nullable=False, default="create", server_default="create"
    )
    apply_policy: Mapped[str | None] = mapped_column(String(24))
    include_warning_rows: Mapped[bool | None] = mapped_column(Boolean)
    parent_batch_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    created_by_scope: Mapped[str] = mapped_column(String(32), nullable=False)
    created_by_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="draft", server_default="draft"
    )
    preview_version: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    preview_fingerprint: Mapped[str | None] = mapped_column(CHAR(64))
    total_rows: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    planned_create_rows: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    planned_update_rows: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    planned_skip_rows: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    warning_rows: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    error_rows: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    created_rows: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    updated_rows: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    skipped_rows: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    failed_rows: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    uncertain_rows: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    cancelled_rows: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    processed_rows: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    row_version: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=1, server_default="1"
    )
    last_error_code: Mapped[str | None] = mapped_column(String(128))
    preview_expires_at: Mapped[datetime | None] = mapped_column(UTC_TIMESTAMP)
    cancel_requested_at: Mapped[datetime | None] = mapped_column(UTC_TIMESTAMP)
    confirmed_at: Mapped[datetime | None] = mapped_column(UTC_TIMESTAMP)
    started_at: Mapped[datetime | None] = mapped_column(UTC_TIMESTAMP)
    finished_at: Mapped[datetime | None] = mapped_column(UTC_TIMESTAMP)
    retention_until: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False, default=utc_now)
