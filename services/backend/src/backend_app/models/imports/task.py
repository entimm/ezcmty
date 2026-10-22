"""Persistent import facts. Transactions are owned by the calling service."""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend_app.core.identifiers import new_id
from backend_app.db.base import Base
from backend_app.db.types import UTC_TIMESTAMP
from backend_app.models.admin import utc_now


class ImportTask(Base):
    __tablename__ = "import_tasks"
    __table_args__ = (
        ForeignKeyConstraint(["batch_id"], ["import_batches.id"], name="fk_import_task_batch"),
        UniqueConstraint("batch_id", "phase", name="uq_import_task_phase"),
        CheckConstraint(
            "phase IN ('parse','precheck','apply','artifact')", name="ck_import_task_phase"
        ),
        CheckConstraint(
            "status IN ('ready','running','completed','paused','cancelled')",
            name="ck_import_task_status",
        ),
        CheckConstraint(
            "(status = 'running') = (lease_expires_at IS NOT NULL)", name="ck_import_task_lease"
        ),
        CheckConstraint(
            "attempt_count >= 0 AND progress_done >= 0 AND progress_total >= 0 AND "
            "progress_done <= progress_total",
            name="ck_import_task_progress",
        ),
        CheckConstraint(
            "jsonb_typeof(checkpoint) = 'object' AND checkpoint ? 'schema_version' AND "
            "jsonb_typeof(checkpoint->'schema_version') = 'number' AND "
            "checkpoint->>'schema_version' = '1'",
            name="ck_import_task_checkpoint",
        ),
        Index(
            "ix_import_task_ready",
            "status",
            "next_run_at",
            "id",
            postgresql_where=text("status = 'ready'"),
        ),
        Index(
            "ix_import_task_running",
            "status",
            "lease_expires_at",
            "id",
            postgresql_where=text("status = 'running'"),
        ),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_id)
    batch_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    phase: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="ready", server_default="ready"
    )
    next_run_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False)
    attempt_count: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(UTC_TIMESTAMP)
    progress_done: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    progress_total: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    checkpoint: Mapped[dict[str, Any]] = mapped_column(JSONB(none_as_null=True), nullable=False)
    last_error_code: Mapped[str | None] = mapped_column(String(128))
    started_at: Mapped[datetime | None] = mapped_column(UTC_TIMESTAMP)
    completed_at: Mapped[datetime | None] = mapped_column(UTC_TIMESTAMP)
    created_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False, default=utc_now)
