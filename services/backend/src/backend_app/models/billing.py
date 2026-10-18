from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CHAR,
    BigInteger,
    CheckConstraint,
    Computed,
    Date,
    ForeignKeyConstraint,
    Index,
    Numeric,
    SmallInteger,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend_app.db.base import Base
from backend_app.db.types import UTC_TIMESTAMP

UUID_TYPE = UUID(as_uuid=False)
LIMIT = 9007199254740991


class FeeBasisVersion(Base):
    __tablename__ = "property_fee_basis_versions"
    __table_args__ = (
        UniqueConstraint("house_id", "version_no", name="uq_fee_basis_house_version"),
        UniqueConstraint("house_id", "id", name="uq_fee_basis_house_id"),
        ForeignKeyConstraint(["house_id"], ["houses.id"], name="fk_fee_basis_house"),
        ForeignKeyConstraint(["created_by"], ["admin_accounts.id"], name="fk_fee_basis_creator"),
        CheckConstraint("version_no > 0", name="ck_fee_basis_version"),
        CheckConstraint("EXTRACT(DAY FROM effective_from_month) = 1", name="ck_fee_basis_month"),
        CheckConstraint(
            "house_usage IN ('residential','commercial','office','other')",
            name="ck_fee_basis_usage",
        ),
        CheckConstraint("area_sqm IS NULL OR area_sqm > 0", name="ck_fee_basis_area"),
        CheckConstraint(
            f"unit_price_cents IS NULL OR unit_price_cents BETWEEN 0 AND {LIMIT}",
            name="ck_fee_basis_rate",
        ),
        CheckConstraint(
            f"fixed_amount_cents IS NULL OR fixed_amount_cents BETWEEN 0 AND {LIMIT}",
            name="ck_fee_basis_fixed",
        ),
        CheckConstraint(
            "fixed_amount_cents IS NOT NULL OR (area_sqm IS NOT NULL AND "
            "unit_price_cents IS NOT NULL)",
            name="ck_fee_basis_inputs",
        ),
        CheckConstraint(
            f"fixed_amount_cents IS NOT NULL OR round(area_sqm * unit_price_cents) <= {LIMIT}",
            name="ck_fee_basis_calculated_range",
        ),
        CheckConstraint("btrim(change_reason) <> ''", name="ck_fee_basis_reason"),
        Index(
            "ix_fee_basis_effective",
            "house_id",
            text("effective_from_month DESC"),
            text("version_no DESC"),
        ),
        Index("ix_fee_basis_creator", "created_by"),
    )
    id: Mapped[str] = mapped_column(UUID_TYPE, primary_key=True)
    house_id: Mapped[str] = mapped_column(UUID_TYPE, nullable=False)
    version_no: Mapped[int] = mapped_column(BigInteger, nullable=False)
    effective_from_month: Mapped[date] = mapped_column(Date, nullable=False)
    house_usage: Mapped[str] = mapped_column(String(32), nullable=False)
    area_sqm: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    unit_price_cents: Mapped[int | None] = mapped_column(BigInteger)
    fixed_amount_cents: Mapped[int | None] = mapped_column(BigInteger)
    change_reason: Mapped[str] = mapped_column(String(1000), nullable=False)
    created_by: Mapped[str] = mapped_column(UUID_TYPE, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False)


class Bill(Base):
    __tablename__ = "bills"
    __table_args__ = (
        UniqueConstraint("property_company_id", "id", name="uq_bill_company_id"),
        ForeignKeyConstraint(
            ["property_company_id", "community_id"],
            ["communities.property_company_id", "communities.id"],
            name="fk_bill_community",
        ),
        ForeignKeyConstraint(
            ["community_id", "house_id"], ["houses.community_id", "houses.id"], name="fk_bill_house"
        ),
        ForeignKeyConstraint(
            ["house_id", "basis_version_id"],
            ["property_fee_basis_versions.house_id", "property_fee_basis_versions.id"],
            name="fk_bill_basis",
        ),
        ForeignKeyConstraint(["created_by"], ["admin_accounts.id"], name="fk_bill_creator"),
        ForeignKeyConstraint(["voided_by"], ["admin_accounts.id"], name="fk_bill_void_actor"),
        CheckConstraint(
            "bill_type = 'property_fee' AND period_granularity = 'month'",
            name="ck_bill_type_period",
        ),
        CheckConstraint(
            "EXTRACT(DAY FROM period_start) = 1 AND period_end = (period_start + "
            "INTERVAL '1 month')::date",
            name="ck_bill_month",
        ),
        CheckConstraint(
            f"receivable_cents BETWEEN 0 AND {LIMIT} AND settled_cents BETWEEN 0 AND "
            f"receivable_cents",
            name="ck_bill_amounts",
        ),
        CheckConstraint(
            "(amount_source = 'basis' AND basis_version_id IS NOT NULL AND "
            "calculation_rule_version IS NOT NULL AND calculation_rule_version = 1 "
            "AND manual_amount_reason IS NULL) OR (amount_source = 'manual' AND "
            "calculation_rule_version IS NULL AND manual_amount_reason IS NOT NULL "
            "AND btrim(manual_amount_reason) <> '')",
            name="ck_bill_source",
        ),
        CheckConstraint(
            "(lifecycle_status = 'active' AND void_reason IS NULL AND voided_at IS "
            "NULL AND voided_by IS NULL) OR (lifecycle_status = 'voided' AND "
            "settled_cents = 0 AND void_reason IS NOT NULL AND btrim(void_reason) <> "
            "'' AND voided_at IS NOT NULL AND voided_by IS NOT NULL)",
            name="ck_bill_lifecycle",
        ),
        CheckConstraint(
            "house_label_snapshot <> '' AND row_version > 0", name="ck_bill_snapshot_version"
        ),
        CheckConstraint(
            "external_bill_no IS NULL OR (external_bill_no <> '' AND "
            "external_bill_no = btrim(external_bill_no))",
            name="ck_bill_external",
        ),
        Index(
            "uq_bills_active_house_month",
            "house_id",
            "bill_type",
            "period_start",
            unique=True,
            postgresql_where=text("lifecycle_status = 'active' AND period_granularity = 'month'"),
        ),
        Index(
            "ix_bill_community_period",
            "property_company_id",
            "community_id",
            text("period_start DESC"),
            text("id DESC"),
        ),
        Index("ix_bill_house_period", "house_id", text("period_start DESC"), text("id DESC")),
        Index(
            "ix_bill_pending",
            "property_company_id",
            "community_id",
            text("period_start DESC"),
            text("id DESC"),
            postgresql_where=text("lifecycle_status = 'active' AND outstanding_cents > 0"),
        ),
        Index(
            "ix_bill_due",
            "property_company_id",
            "due_date",
            "id",
            postgresql_where=text(
                "lifecycle_status = 'active' AND outstanding_cents > 0 AND due_date IS NOT NULL"
            ),
        ),
        Index(
            "ix_bill_external",
            "property_company_id",
            "external_bill_no",
            postgresql_where=text("external_bill_no IS NOT NULL"),
        ),
        Index("ix_bill_house_fk", "community_id", "house_id"),
        Index("ix_bill_basis_fk", "house_id", "basis_version_id"),
        Index("ix_bill_creator", "created_by"),
        Index("ix_bill_void_actor", "voided_by"),
    )
    id: Mapped[str] = mapped_column(UUID_TYPE, primary_key=True)
    property_company_id: Mapped[str] = mapped_column(UUID_TYPE, nullable=False)
    community_id: Mapped[str] = mapped_column(UUID_TYPE, nullable=False)
    house_id: Mapped[str] = mapped_column(UUID_TYPE, nullable=False)
    bill_type: Mapped[str] = mapped_column(String(32), nullable=False)
    period_granularity: Mapped[str] = mapped_column(String(16), nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    external_bill_no: Mapped[str | None] = mapped_column(String(128))
    basis_version_id: Mapped[str | None] = mapped_column(UUID_TYPE)
    amount_source: Mapped[str] = mapped_column(String(16), nullable=False)
    calculation_rule_version: Mapped[int | None] = mapped_column(SmallInteger)
    receivable_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    settled_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    outstanding_cents: Mapped[int] = mapped_column(
        BigInteger,
        Computed(
            "CASE WHEN lifecycle_status = 'voided' THEN 0 ELSE receivable_cents - "
            "settled_cents END",
            persisted=True,
        ),
        nullable=False,
    )
    lifecycle_status: Mapped[str] = mapped_column(String(16), nullable=False)
    settlement_status: Mapped[str | None] = mapped_column(
        String(32),
        Computed(
            "CASE WHEN lifecycle_status = 'voided' THEN NULL WHEN settled_cents = "
            "receivable_cents THEN 'settled' WHEN settled_cents = 0 THEN 'unpaid' "
            "ELSE 'partially_settled' END",
            persisted=True,
        ),
    )
    due_date: Mapped[date | None] = mapped_column(Date)
    house_label_snapshot: Mapped[str] = mapped_column(String(512), nullable=False)
    manual_amount_reason: Mapped[str | None] = mapped_column(String(1000))
    void_reason: Mapped[str | None] = mapped_column(String(1000))
    voided_at: Mapped[datetime | None] = mapped_column(UTC_TIMESTAMP)
    voided_by: Mapped[str | None] = mapped_column(UUID_TYPE)
    row_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_by: Mapped[str] = mapped_column(UUID_TYPE, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False)


class BillOperation(Base):
    __tablename__ = "bill_operations"
    __table_args__ = (
        UniqueConstraint("property_company_id", "idempotency_key", name="uq_bill_operation_key"),
        UniqueConstraint("bill_id", "bill_version", name="uq_bill_operation_version"),
        UniqueConstraint("bill_id", "id", name="uq_bill_operation_bill_id"),
        ForeignKeyConstraint(
            ["property_company_id", "bill_id"],
            ["bills.property_company_id", "bills.id"],
            name="fk_bill_operation_bill",
        ),
        ForeignKeyConstraint(
            ["property_company_id", "actor_id"],
            ["admin_accounts.property_company_id", "admin_accounts.id"],
            name="fk_bill_operation_actor",
        ),
        CheckConstraint(
            "action IN ('create','update','receipt','online_receipt','correct_receipt',"
            "'reverse_receipt','void')",
            name="ck_bill_operation_action",
        ),
        CheckConstraint(
            "(actor_type = 'admin' AND actor_id IS NOT NULL AND response_status IS NOT NULL "
            "AND action <> 'online_receipt') OR (actor_type = 'system' AND actor_id IS NULL "
            "AND response_status IS NULL AND action = 'online_receipt')",
            name="ck_bill_operation_actor",
        ),
        CheckConstraint(
            "action NOT IN ('correct_receipt','reverse_receipt','void') OR (reason "
            "IS NOT NULL AND btrim(reason) <> '')",
            name="ck_bill_operation_reason",
        ),
        CheckConstraint(
            "idempotency_key ~ '^[A-Za-z0-9_-]{1,128}$' AND request_fingerprint ~ "
            "'^[0-9a-f]{64}$' AND bill_version > 0",
            name="ck_bill_operation_identifiers",
        ),
        Index("ix_bill_operation_actor", "property_company_id", "actor_id"),
    )
    id: Mapped[str] = mapped_column(UUID_TYPE, primary_key=True)
    property_company_id: Mapped[str] = mapped_column(UUID_TYPE, nullable=False)
    bill_id: Mapped[str] = mapped_column(UUID_TYPE, nullable=False)
    bill_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    result: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    response_status: Mapped[int | None] = mapped_column(SmallInteger)
    reason: Mapped[str | None] = mapped_column(String(1000))
    actor_type: Mapped[str] = mapped_column(String(16), nullable=False, default="admin")
    actor_id: Mapped[str | None] = mapped_column(UUID_TYPE)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False)


class BillSettlementEntry(Base):
    __tablename__ = "bill_settlement_entries"
    __table_args__ = (
        UniqueConstraint("bill_id", "id", name="uq_bill_entry_bill_id"),
        ForeignKeyConstraint(["bill_id"], ["bills.id"], name="fk_bill_entry_bill"),
        ForeignKeyConstraint(
            ["bill_id", "operation_id"],
            ["bill_operations.bill_id", "bill_operations.id"],
            name="fk_bill_entry_operation",
        ),
        ForeignKeyConstraint(
            ["bill_id", "reverses_entry_id"],
            ["bill_settlement_entries.bill_id", "bill_settlement_entries.id"],
            name="fk_bill_entry_original",
        ),
        ForeignKeyConstraint(
            ["bill_id", "payment_order_item_id"],
            ["payment_order_items.bill_id", "payment_order_items.id"],
            name="fk_bill_entry_payment_item",
        ),
        CheckConstraint(
            "(source_type = 'offline' AND payment_order_item_id IS NULL) OR "
            "(source_type = 'online_payment' AND payment_order_item_id IS NOT NULL "
            "AND entry_type = 'receipt' AND received_on IS NOT NULL)",
            name="ck_bill_entry_source",
        ),
        CheckConstraint(f"amount_cents BETWEEN -{LIMIT} AND {LIMIT}", name="ck_bill_entry_range"),
        CheckConstraint(
            "(entry_type = 'receipt' AND amount_cents > 0 AND reverses_entry_id IS "
            "NULL) OR (entry_type = 'reversal' AND amount_cents < 0 AND "
            "reverses_entry_id IS NOT NULL AND received_on IS NULL)",
            name="ck_bill_entry_type",
        ),
        Index(
            "uq_bill_entry_reversed",
            "reverses_entry_id",
            unique=True,
            postgresql_where=text("reverses_entry_id IS NOT NULL"),
        ),
        Index("ix_bill_entry_time", "bill_id", text("created_at DESC"), text("id DESC")),
        Index("ix_bill_entry_operation", "bill_id", "operation_id"),
        Index(
            "uq_bill_entry_payment_item",
            "payment_order_item_id",
            unique=True,
            postgresql_where=text("payment_order_item_id IS NOT NULL"),
        ),
        Index("ix_bill_entry_payment_item_fk", "bill_id", "payment_order_item_id"),
    )
    id: Mapped[str] = mapped_column(UUID_TYPE, primary_key=True)
    bill_id: Mapped[str] = mapped_column(UUID_TYPE, nullable=False)
    operation_id: Mapped[str] = mapped_column(UUID_TYPE, nullable=False)
    entry_type: Mapped[str] = mapped_column(String(16), nullable=False)
    source_type: Mapped[str] = mapped_column(String(16), nullable=False)
    payment_order_item_id: Mapped[str | None] = mapped_column(UUID_TYPE)
    amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reverses_entry_id: Mapped[str | None] = mapped_column(UUID_TYPE)
    received_on: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False)
