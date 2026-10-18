from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
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


class PaymentReconciliationRun(Base):
    __tablename__ = "payment_reconciliation_runs"
    __table_args__ = (
        UniqueConstraint(
            "business_date",
            "statement_type",
            "service_provider_merchant_no",
            "merchant_no",
            name="uq_payment_reconciliation_scope",
            postgresql_nulls_not_distinct=True,
        ),
        CheckConstraint(
            "(statement_type IN ('trade','profit_sharing') AND merchant_no IS NOT NULL AND "
            "btrim(merchant_no) <> '') OR (statement_type = 'platform_fundflow' AND "
            "merchant_no IS NULL)",
            name="ck_payment_reconciliation_scope",
        ),
        CheckConstraint(
            "btrim(service_provider_merchant_no) <> '' AND ((statement_hash_type IS NULL "
            "AND statement_hash IS NULL) OR (statement_hash_type IS NOT NULL AND "
            "btrim(statement_hash_type) <> '' AND statement_hash IS NOT NULL AND "
            "btrim(statement_hash) <> ''))",
            name="ck_payment_reconciliation_source",
        ),
        CheckConstraint(
            "status IN ('ready','running','completed','failed') AND (status <> 'completed' "
            "OR (statement_hash IS NOT NULL AND finished_at IS NOT NULL)) AND (status NOT "
            "IN ('ready','running') OR finished_at IS NULL) AND jsonb_typeof(summary) = "
            "'object'",
            name="ck_payment_reconciliation_status",
        ),
        Index("ix_payment_reconciliation_date", "business_date", "statement_type", "id"),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_id)
    business_date: Mapped[date] = mapped_column(Date, nullable=False)
    statement_type: Mapped[str] = mapped_column(String(32), nullable=False)
    service_provider_merchant_no: Mapped[str] = mapped_column(String(64), nullable=False)
    merchant_no: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ready")
    statement_hash_type: Mapped[str | None] = mapped_column(String(32))
    statement_hash: Mapped[str | None] = mapped_column(String(256))
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    finished_at: Mapped[datetime | None] = mapped_column(UTC_TIMESTAMP)
    created_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False, default=utc_now)


class PaymentReconciliationDiscrepancy(Base):
    __tablename__ = "payment_reconciliation_discrepancies"
    __table_args__ = (
        UniqueConstraint(
            "reconciliation_run_id",
            "difference_type",
            "reference_key",
            name="uq_payment_reconciliation_difference",
        ),
        ForeignKeyConstraint(
            ["reconciliation_run_id"],
            ["payment_reconciliation_runs.id"],
            name="fk_payment_difference_run",
        ),
        ForeignKeyConstraint(
            ["payment_order_id"], ["payment_orders.id"], name="fk_payment_difference_order"
        ),
        ForeignKeyConstraint(
            ["payment_order_id", "profit_sharing_order_item_id"],
            ["profit_sharing_order_items.payment_order_id", "profit_sharing_order_items.id"],
            name="fk_payment_difference_sharing_item",
        ),
        ForeignKeyConstraint(
            ["resolved_by"], ["admin_accounts.id"], name="fk_payment_difference_resolver"
        ),
        CheckConstraint(
            "difference_type IN "
            "('channel_only','local_only','amount_mismatch','status_mismatch','unclassified"
            "') AND btrim(reference_key) <> ''",
            name="ck_payment_difference_identity",
        ),
        CheckConstraint(
            "profit_sharing_order_item_id IS NULL OR payment_order_id IS NOT NULL",
            name="ck_payment_difference_association",
        ),
        CheckConstraint(
            "status IN ('open','observing','resolved') AND (status <> 'resolved' OR "
            "resolved_at IS NOT NULL) AND jsonb_typeof(evidence) = 'object'",
            name="ck_payment_difference_status",
        ),
        Index("ix_payment_difference_run_status", "reconciliation_run_id", "status", "id"),
        Index("ix_payment_difference_order", "payment_order_id", "id"),
        Index(
            "ix_payment_difference_sharing_item", "payment_order_id", "profit_sharing_order_item_id"
        ),
        Index("ix_payment_difference_resolver", "resolved_by"),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_id)
    reconciliation_run_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    difference_type: Mapped[str] = mapped_column(String(32), nullable=False)
    reference_key: Mapped[str] = mapped_column(String(256), nullable=False)
    payment_order_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    profit_sharing_order_item_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    expected_cents: Mapped[int | None] = mapped_column(BigInteger)
    actual_cents: Mapped[int | None] = mapped_column(BigInteger)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    resolved_at: Mapped[datetime | None] = mapped_column(UTC_TIMESTAMP)
    resolved_by: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    resolution_note: Mapped[str | None] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False, default=utc_now)
