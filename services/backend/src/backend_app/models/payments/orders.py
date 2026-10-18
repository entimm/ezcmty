from datetime import datetime

from sqlalchemy import (
    CHAR,
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


class PaymentOrder(Base):
    __tablename__ = "payment_orders"
    __table_args__ = (
        UniqueConstraint("order_no", name="uq_payment_order_number"),
        UniqueConstraint("payer_user_id", "idempotency_key", name="uq_payment_order_key"),
        UniqueConstraint("property_company_id", "id", name="uq_payment_order_company_id"),
        ForeignKeyConstraint(
            ["property_company_id", "merchant_binding_id"],
            ["property_merchant_bindings.property_company_id", "property_merchant_bindings.id"],
            name="fk_payment_order_binding",
        ),
        ForeignKeyConstraint(
            ["property_company_id", "rule_version_id"],
            ["profit_sharing_rule_versions.property_company_id", "profit_sharing_rule_versions.id"],
            name="fk_payment_order_rule",
        ),
        ForeignKeyConstraint(
            ["payer_user_id"], ["miniapp_users.id"], name="fk_payment_order_payer"
        ),
        CheckConstraint(
            "amount_cents BETWEEN 1 AND 9007199254740991 AND (payer_total_cents IS NULL OR "
            "payer_total_cents BETWEEN 0 AND 9007199254740991)",
            name="ck_payment_order_amount",
        ),
        CheckConstraint(
            "status IN ('pending','unknown','payable','closing','succeeded','closed')",
            name="ck_payment_order_status",
        ),
        CheckConstraint(
            "(status = 'succeeded' AND channel_transaction_no IS NOT NULL AND "
            "btrim(channel_transaction_no) <> '' AND paid_at IS NOT NULL AND closed_at IS "
            "NULL) OR (status = 'closed' AND closed_at IS NOT NULL AND paid_at IS NULL AND "
            "channel_transaction_no IS NULL) OR (status IN "
            "('pending','unknown','payable','closing') AND paid_at IS NULL AND closed_at "
            "IS NULL AND channel_transaction_no IS NULL)",
            name="ck_payment_order_confirmation",
        ),
        CheckConstraint(
            "btrim(order_no) <> '' AND idempotency_key ~ '^[A-Za-z0-9_-]{1,128}$' AND "
            "request_fingerprint ~ '^[0-9a-f]{64}$' AND expires_at > created_at",
            name="ck_payment_order_identifiers",
        ),
        Index(
            "uq_payment_order_transaction",
            "channel_transaction_no",
            unique=True,
            postgresql_where=text("channel_transaction_no IS NOT NULL"),
        ),
        Index(
            "ix_payment_order_payer_time", "payer_user_id", text("created_at DESC"), text("id DESC")
        ),
        Index(
            "ix_payment_order_company_time",
            "property_company_id",
            text("created_at DESC"),
            text("id DESC"),
        ),
        Index("ix_payment_order_binding", "property_company_id", "merchant_binding_id"),
        Index("ix_payment_order_rule", "property_company_id", "rule_version_id"),
        Index(
            "ix_payment_order_expiry",
            "expires_at",
            "id",
            postgresql_where=text("status IN ('pending','unknown','payable','closing')"),
        ),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_id)
    property_company_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    payer_user_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    merchant_binding_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    rule_version_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    order_no: Mapped[str] = mapped_column(String(64), nullable=False)
    channel_transaction_no: Mapped[str | None] = mapped_column(String(64))
    amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    payer_total_cents: Mapped[int | None] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    prepay_token: Mapped[str | None] = mapped_column(String(256))
    expires_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False)
    paid_at: Mapped[datetime | None] = mapped_column(UTC_TIMESTAMP)
    closed_at: Mapped[datetime | None] = mapped_column(UTC_TIMESTAMP)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False, default=utc_now)


class PaymentOrderItem(Base):
    __tablename__ = "payment_order_items"
    __table_args__ = (
        UniqueConstraint("payment_order_id", "bill_id", name="uq_payment_item_order_bill"),
        UniqueConstraint("bill_id", "id", name="uq_payment_item_bill_id"),
        ForeignKeyConstraint(
            ["property_company_id", "payment_order_id"],
            ["payment_orders.property_company_id", "payment_orders.id"],
            name="fk_payment_item_order",
        ),
        ForeignKeyConstraint(
            ["property_company_id", "bill_id"],
            ["bills.property_company_id", "bills.id"],
            name="fk_payment_item_bill",
        ),
        CheckConstraint(
            "amount_cents BETWEEN 1 AND 9007199254740991", name="ck_payment_item_amount"
        ),
        Index("ix_payment_item_company_order", "property_company_id", "payment_order_id"),
        Index("ix_payment_item_company_bill", "property_company_id", "bill_id"),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_id)
    property_company_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    payment_order_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    bill_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False, default=utc_now)


class BillPaymentReservation(Base):
    __tablename__ = "bill_payment_reservations"
    __table_args__ = (
        ForeignKeyConstraint(["bill_id"], ["bills.id"], name="fk_payment_reservation_bill"),
        ForeignKeyConstraint(
            ["payment_order_id", "bill_id"],
            ["payment_order_items.payment_order_id", "payment_order_items.bill_id"],
            name="fk_payment_reservation_item",
        ),
        Index("ix_payment_reservation_order", "payment_order_id"),
    )
    bill_id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    payment_order_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False, default=utc_now)
