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
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend_app.core.identifiers import new_id
from backend_app.db.base import Base
from backend_app.db.types import UTC_TIMESTAMP
from backend_app.models.admin import utc_now


class ImportBatchEvent(Base):
    __tablename__ = "import_batch_events"
    __table_args__ = (
        ForeignKeyConstraint(["batch_id"], ["import_batches.id"], name="fk_import_event_batch"),
        ForeignKeyConstraint(
            ["actor_scope", "actor_id"],
            ["admin_accounts.scope", "admin_accounts.id"],
            name="fk_import_event_actor",
        ),
        ForeignKeyConstraint(["task_id"], ["import_tasks.id"], name="fk_import_event_task"),
        UniqueConstraint("batch_id", "sequence_no", name="uq_import_event_sequence"),
        UniqueConstraint("batch_id", "event_key", name="uq_import_event_key"),
        CheckConstraint(
            "sequence_no > 0 AND (task_attempt IS NULL OR task_attempt > 0)",
            name="ck_import_event_sequence",
        ),
        CheckConstraint("(actor_scope IS NULL) = (actor_id IS NULL)", name="ck_import_event_actor"),
        CheckConstraint("jsonb_typeof(safe_metadata) = 'object'", name="ck_import_event_metadata"),
        CheckConstraint(
            "(from_status IS NULL OR from_status IN "
            "('draft','uploading','prechecking','preview_ready','executing','completed','"
            "partial_failed','failed','blocked','cancel_requested','cancelled','expired')"
            ") AND (to_status IS NULL OR to_status IN "
            "('draft','uploading','prechecking','preview_ready','executing','completed','"
            "partial_failed','failed','blocked','cancel_requested','cancelled','expired')"
            ")",
            name="ck_import_event_status",
        ),
        Index("ix_import_event_task", "task_id", "created_at"),
        Index("ix_import_event_actor", "actor_scope", "actor_id"),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_id)
    batch_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    sequence_no: Mapped[int] = mapped_column(BigInteger, nullable=False)
    event_key: Mapped[str] = mapped_column(String(128), nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(24))
    to_status: Mapped[str | None] = mapped_column(String(24))
    actor_scope: Mapped[str | None] = mapped_column(String(32))
    actor_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    task_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    task_attempt: Mapped[int | None] = mapped_column(BigInteger)
    safe_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB(none_as_null=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False, default=utc_now)
