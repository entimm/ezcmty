"""Persistent import facts. Transactions are owned by the calling service."""

from datetime import datetime

from sqlalchemy import (
    CHAR,
    BigInteger,
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend_app.core.identifiers import new_id
from backend_app.db.base import Base
from backend_app.db.types import UTC_TIMESTAMP
from backend_app.models.admin import utc_now


class ImportArtifact(Base):
    __tablename__ = "import_artifacts"
    __table_args__ = (
        ForeignKeyConstraint(["batch_id"], ["import_batches.id"], name="fk_import_artifact_batch"),
        UniqueConstraint(
            "batch_id", "artifact_kind", "generation", name="uq_import_artifact_generation"
        ),
        CheckConstraint(
            "(artifact_kind = 'source' AND source_preview_version IS NULL) OR "
            "(artifact_kind = 'error_rows' AND source_preview_version IS NOT NULL "
            "AND source_preview_version > 0)",
            name="ck_import_artifact_kind",
        ),
        CheckConstraint(
            "generation > 0 AND byte_size >= 0 AND (row_count IS NULL OR row_count >= 0)",
            name="ck_import_artifact_size",
        ),
        CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="ck_import_artifact_digest"),
        Index(
            "ix_import_artifact_source",
            "batch_id",
            unique=True,
            postgresql_where=text("artifact_kind = 'source'"),
        ),
        Index("ix_import_artifact_expiry", "expires_at", "id"),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_id)
    batch_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    artifact_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    generation: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    source_preview_version: Mapped[int | None] = mapped_column(BigInteger)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    original_filename: Mapped[str | None] = mapped_column(String(255))
    media_type: Mapped[str] = mapped_column(String(128), nullable=False)
    sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    row_count: Mapped[int | None] = mapped_column(BigInteger)
    expires_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(UTC_TIMESTAMP)
    created_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False, default=utc_now)
