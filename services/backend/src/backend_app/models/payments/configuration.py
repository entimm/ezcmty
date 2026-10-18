from datetime import datetime

from sqlalchemy import (
    CHAR,
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    Integer,
    SmallInteger,
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


class PropertyMerchantBinding(Base):
    __tablename__ = "property_merchant_bindings"
    __table_args__ = (
        UniqueConstraint("property_company_id", "id", name="uq_merchant_binding_company_id"),
        UniqueConstraint("property_company_id", "idempotency_key", name="uq_merchant_binding_key"),
        ForeignKeyConstraint(
            ["property_company_id"], ["property_companies.id"], name="fk_merchant_binding_company"
        ),
        ForeignKeyConstraint(
            ["created_by"], ["admin_accounts.id"], name="fk_merchant_binding_creator"
        ),
        CheckConstraint(
            "btrim(service_provider_merchant_no) <> '' AND btrim(merchant_no) <> '' AND "
            "btrim(merchant_name) <> ''",
            name="ck_merchant_binding_identity",
        ),
        CheckConstraint(
            "(max_ratio_bps IS NULL AND ratio_checked_at IS NULL) OR (max_ratio_bps IS NOT "
            "NULL AND max_ratio_bps BETWEEN 0 AND 10000 AND ratio_checked_at IS NOT NULL)",
            name="ck_merchant_binding_ratio",
        ),
        CheckConstraint(
            "row_version > 0 AND idempotency_key ~ '^[A-Za-z0-9_-]{1,128}$' AND "
            "request_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_merchant_binding_identifiers",
        ),
        Index(
            "uq_merchant_binding_enabled",
            "property_company_id",
            unique=True,
            postgresql_where=text("enabled"),
        ),
        Index("ix_merchant_binding_creator", "created_by"),
        Index(
            "ix_merchant_binding_identity",
            "service_provider_merchant_no",
            "merchant_no",
            "created_at",
        ),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_id)
    property_company_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    service_provider_merchant_no: Mapped[str] = mapped_column(String(64), nullable=False)
    merchant_no: Mapped[str] = mapped_column(String(64), nullable=False)
    merchant_name: Mapped[str] = mapped_column(String(256), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    max_ratio_bps: Mapped[int | None] = mapped_column(Integer)
    ratio_checked_at: Mapped[datetime | None] = mapped_column(UTC_TIMESTAMP)
    created_by: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    row_version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False, default=utc_now)


class ProfitSharingRuleVersion(Base):
    __tablename__ = "profit_sharing_rule_versions"
    __table_args__ = (
        UniqueConstraint(
            "property_company_id", "version_no", name="uq_sharing_rule_company_version"
        ),
        UniqueConstraint("property_company_id", "id", name="uq_sharing_rule_company_id"),
        UniqueConstraint("property_company_id", "idempotency_key", name="uq_sharing_rule_key"),
        ForeignKeyConstraint(
            ["property_company_id"], ["property_companies.id"], name="fk_sharing_rule_company"
        ),
        ForeignKeyConstraint(["created_by"], ["admin_accounts.id"], name="fk_sharing_rule_creator"),
        CheckConstraint(
            "version_no > 0 AND calculation_version = 1", name="ck_sharing_rule_version"
        ),
        CheckConstraint(
            "idempotency_key ~ '^[A-Za-z0-9_-]{1,128}$' AND request_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_sharing_rule_identifiers",
        ),
        Index("ix_sharing_rule_creator", "created_by"),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_id)
    property_company_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    version_no: Mapped[int] = mapped_column(BigInteger, nullable=False)
    calculation_version: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    created_by: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False, default=utc_now)


class ProfitSharingRuleVersionItem(Base):
    __tablename__ = "profit_sharing_rule_version_items"
    __table_args__ = (
        UniqueConstraint(
            "rule_version_id", "receiver_type", "receiver_account", name="uq_sharing_rule_receiver"
        ),
        ForeignKeyConstraint(
            ["rule_version_id"],
            ["profit_sharing_rule_versions.id"],
            name="fk_sharing_rule_item_version",
        ),
        CheckConstraint(
            "receiver_type = 'merchant' AND relation_type = 'service_provider' AND "
            "btrim(receiver_account) <> '' AND btrim(receiver_name) <> ''",
            name="ck_sharing_rule_receiver",
        ),
        CheckConstraint("rate_bps BETWEEN 0 AND 10000", name="ck_sharing_rule_rate"),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_id)
    rule_version_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    receiver_type: Mapped[str] = mapped_column(String(32), nullable=False, default="merchant")
    receiver_account: Mapped[str] = mapped_column(String(128), nullable=False)
    receiver_name: Mapped[str] = mapped_column(String(256), nullable=False)
    relation_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="service_provider"
    )
    rate_bps: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False, default=utc_now)
