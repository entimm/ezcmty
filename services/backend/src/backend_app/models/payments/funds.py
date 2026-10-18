from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
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


class ProfitSharingAllocation(Base):
    __tablename__ = "profit_sharing_allocations"
    __table_args__ = (
        UniqueConstraint(
            "payment_order_id", "rule_version_item_id", name="uq_sharing_allocation_receiver"
        ),
        UniqueConstraint("payment_order_id", "id", name="uq_sharing_allocation_payment_id"),
        ForeignKeyConstraint(
            ["payment_order_id"], ["payment_orders.id"], name="fk_sharing_allocation_payment"
        ),
        ForeignKeyConstraint(
            ["rule_version_item_id"],
            ["profit_sharing_rule_version_items.id"],
            name="fk_sharing_allocation_rule_item",
        ),
        CheckConstraint(
            "amount_cents BETWEEN 1 AND 9007199254740991", name="ck_sharing_allocation_amount"
        ),
        Index("ix_sharing_allocation_rule_item", "rule_version_item_id"),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_id)
    payment_order_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    rule_version_item_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False, default=utc_now)


class ProfitSharingOrder(Base):
    __tablename__ = "profit_sharing_orders"
    __table_args__ = (
        UniqueConstraint("order_no", name="uq_sharing_order_number"),
        UniqueConstraint("payment_order_id", "id", name="uq_sharing_order_payment_id"),
        ForeignKeyConstraint(
            ["payment_order_id"], ["payment_orders.id"], name="fk_sharing_order_payment"
        ),
        CheckConstraint("order_no ~ '^ps_[A-Za-z0-9_-]+$'", name="ck_sharing_order_number"),
        CheckConstraint(
            "status IN ('pending','unknown','processing','finished','rejected')",
            name="ck_sharing_order_status",
        ),
        Index(
            "uq_sharing_order_inflight",
            "payment_order_id",
            unique=True,
            postgresql_where=text("status IN ('pending','unknown','processing')"),
        ),
        Index("ix_sharing_order_payment_time", "payment_order_id", "created_at", "id"),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_id)
    payment_order_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    order_no: Mapped[str] = mapped_column(String(64), nullable=False)
    channel_order_no: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False, default=utc_now)


class ProfitSharingOrderItem(Base):
    __tablename__ = "profit_sharing_order_items"
    __table_args__ = (
        UniqueConstraint(
            "profit_sharing_order_id", "allocation_id", name="uq_sharing_order_allocation"
        ),
        UniqueConstraint("payment_order_id", "id", name="uq_sharing_order_item_payment_id"),
        ForeignKeyConstraint(
            ["payment_order_id", "profit_sharing_order_id"],
            ["profit_sharing_orders.payment_order_id", "profit_sharing_orders.id"],
            name="fk_sharing_order_item_order",
        ),
        ForeignKeyConstraint(
            ["payment_order_id", "allocation_id"],
            ["profit_sharing_allocations.payment_order_id", "profit_sharing_allocations.id"],
            name="fk_sharing_order_item_allocation",
        ),
        CheckConstraint(
            "amount_cents BETWEEN 1 AND 9007199254740991", name="ck_sharing_order_item_amount"
        ),
        CheckConstraint(
            "result IS NULL OR result IN ('success','failed')", name="ck_sharing_order_item_result"
        ),
        CheckConstraint(
            "(result IS NULL AND finished_at IS NULL) OR (result IS NOT NULL AND "
            "finished_at IS NOT NULL)",
            name="ck_sharing_order_item_finished",
        ),
        Index("ix_sharing_order_item_allocation", "payment_order_id", "allocation_id"),
        Index("ix_sharing_order_item_parent", "payment_order_id", "profit_sharing_order_id"),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_id)
    payment_order_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    profit_sharing_order_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    allocation_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    result: Mapped[str | None] = mapped_column(String(32))
    channel_detail_no: Mapped[str | None] = mapped_column(String(64))
    fail_reason: Mapped[str | None] = mapped_column(String(1000))
    finished_at: Mapped[datetime | None] = mapped_column(UTC_TIMESTAMP)
    created_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False, default=utc_now)


class PaymentUnfreezeOrder(Base):
    __tablename__ = "payment_unfreeze_orders"
    __table_args__ = (
        UniqueConstraint("order_no", name="uq_unfreeze_order_number"),
        ForeignKeyConstraint(
            ["payment_order_id"], ["payment_orders.id"], name="fk_unfreeze_order_payment"
        ),
        CheckConstraint("order_no ~ '^uf_[A-Za-z0-9_-]+$'", name="ck_unfreeze_order_number"),
        CheckConstraint(
            "status IN ('pending','unknown','processing','succeeded','failed','no_remaining')",
            name="ck_unfreeze_order_status",
        ),
        CheckConstraint(
            "unfrozen_cents IS NULL OR unfrozen_cents BETWEEN 0 AND 9007199254740991",
            name="ck_unfreeze_order_amount",
        ),
        CheckConstraint(
            "(status = 'succeeded' AND unfrozen_cents IS NOT NULL AND finished_at IS NOT "
            "NULL) OR (status IN ('failed','no_remaining') AND finished_at IS NOT NULL) OR "
            "(status IN ('pending','unknown','processing') AND finished_at IS NULL)",
            name="ck_unfreeze_order_finished",
        ),
        Index(
            "uq_unfreeze_order_inflight",
            "payment_order_id",
            unique=True,
            postgresql_where=text("status IN ('pending','unknown','processing')"),
        ),
        Index("ix_unfreeze_order_payment_time", "payment_order_id", "created_at", "id"),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_id)
    payment_order_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    order_no: Mapped[str] = mapped_column(String(64), nullable=False)
    channel_order_no: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    unfrozen_cents: Mapped[int | None] = mapped_column(BigInteger)
    channel_detail_no: Mapped[str | None] = mapped_column(String(64))
    fail_reason: Mapped[str | None] = mapped_column(String(1000))
    finished_at: Mapped[datetime | None] = mapped_column(UTC_TIMESTAMP)
    created_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False, default=utc_now)
