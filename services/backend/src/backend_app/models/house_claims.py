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


class HouseClaim(Base):
    __tablename__ = "house_claim_applications"
    __table_args__ = (
        ForeignKeyConstraint(["user_id"], ["miniapp_users.id"], name="fk_house_claim_user"),
        ForeignKeyConstraint(
            ["property_company_id", "community_id"],
            ["communities.property_company_id", "communities.id"],
            name="fk_house_claim_community",
        ),
        ForeignKeyConstraint(
            ["community_id", "house_id"],
            ["houses.community_id", "houses.id"],
            name="fk_house_claim_house",
        ),
        ForeignKeyConstraint(
            ["house_id", "matched_owner_id"],
            ["house_owners.house_id", "house_owners.id"],
            name="fk_house_claim_owner",
        ),
        ForeignKeyConstraint(
            ["property_company_id", "reviewed_by_admin_id"],
            ["admin_accounts.property_company_id", "admin_accounts.id"],
            name="fk_house_claim_reviewer",
        ),
        UniqueConstraint("user_id", "idempotency_key", name="uq_house_claim_key"),
        UniqueConstraint(
            "property_company_id",
            "community_id",
            "house_id",
            "user_id",
            "id",
            name="uq_house_claim_scope_id",
        ),
        CheckConstraint(
            "applicant_name <> '' AND applicant_name = btrim(applicant_name) AND "
            "applicant_phone ~ '^1[3-9][0-9]{9}$' AND house_label_snapshot <> ''",
            name="ck_house_claim_applicant",
        ),
        CheckConstraint(
            "(match_status = 'matched' AND matched_owner_id IS NOT NULL) OR "
            "(match_status = 'unmatched' AND matched_owner_id IS NULL)",
            name="ck_house_claim_match",
        ),
        CheckConstraint(
            "(status = 'pending' AND reviewed_at IS NULL AND reviewed_by_admin_id IS NULL "
            "AND review_reason IS NULL AND cancelled_at IS NULL) OR "
            "(status IN ('approved','rejected') AND reviewed_at IS NOT NULL AND "
            "reviewed_by_admin_id IS NOT NULL AND cancelled_at IS NULL) OR "
            "(status = 'cancelled' AND cancelled_at IS NOT NULL AND reviewed_at IS NULL "
            "AND reviewed_by_admin_id IS NULL AND review_reason IS NULL)",
            name="ck_house_claim_status",
        ),
        CheckConstraint(
            "(review_reason IS NULL OR (review_reason <> '' AND review_reason = "
            "btrim(review_reason))) AND (applicant_remark IS NULL OR "
            "(applicant_remark <> '' AND applicant_remark = btrim(applicant_remark))) AND "
            "(NOT (status = 'rejected' OR (status = 'approved' AND match_status = "
            "'unmatched')) OR review_reason IS NOT NULL)",
            name="ck_house_claim_reasons",
        ),
        CheckConstraint(
            "row_version > 0 AND idempotency_key ~ '^[A-Za-z0-9_-]{1,128}$' AND "
            "request_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_house_claim_keys",
        ),
        Index(
            "uq_house_claim_pending",
            "user_id",
            "house_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
        Index("ix_house_claim_user_time", "user_id", "created_at", "id"),
        Index("ix_house_claim_company_time", "property_company_id", "status", "created_at", "id"),
        Index(
            "ix_house_claim_community_time",
            "property_company_id",
            "community_id",
            "status",
            "created_at",
            "id",
        ),
        Index("ix_house_claim_house_time", "house_id", "created_at", "id"),
        Index("ix_house_claim_house_fk", "community_id", "house_id"),
        Index("ix_house_claim_owner_fk", "house_id", "matched_owner_id"),
        Index("ix_house_claim_reviewer", "property_company_id", "reviewed_by_admin_id"),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    property_company_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    community_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    house_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    house_label_snapshot: Mapped[str] = mapped_column(String(512), nullable=False)
    applicant_name: Mapped[str] = mapped_column(String(80), nullable=False)
    applicant_phone: Mapped[str] = mapped_column(String(11), nullable=False)
    applicant_remark: Mapped[str | None] = mapped_column(String(1000))
    match_status: Mapped[str] = mapped_column(String(16), nullable=False)
    matched_owner_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    reviewed_by_admin_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    reviewed_at: Mapped[datetime | None] = mapped_column(UTC_TIMESTAMP)
    review_reason: Mapped[str | None] = mapped_column(String(1000))
    cancelled_at: Mapped[datetime | None] = mapped_column(UTC_TIMESTAMP)
    row_version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False, default=utc_now)


class ResidentHouseBinding(Base):
    __tablename__ = "resident_house_bindings"
    __table_args__ = (
        ForeignKeyConstraint(
            ["property_company_id", "community_id", "house_id", "user_id", "claim_application_id"],
            [
                "house_claim_applications.property_company_id",
                "house_claim_applications.community_id",
                "house_claim_applications.house_id",
                "house_claim_applications.user_id",
                "house_claim_applications.id",
            ],
            name="fk_resident_binding_origin",
        ),
        ForeignKeyConstraint(
            ["property_company_id", "ended_by_admin_id"],
            ["admin_accounts.property_company_id", "admin_accounts.id"],
            name="fk_resident_binding_admin",
        ),
        ForeignKeyConstraint(
            ["ended_by_user_id"], ["miniapp_users.id"], name="fk_resident_binding_user"
        ),
        UniqueConstraint("claim_application_id", name="uq_resident_binding_claim"),
        CheckConstraint(
            "(status = 'active' AND ended_at IS NULL AND ended_by_user_id IS NULL AND "
            "ended_by_admin_id IS NULL AND end_reason IS NULL) OR (status = 'released' "
            "AND ended_at IS NOT NULL AND ended_by_user_id IS NOT NULL AND "
            "ended_by_user_id = user_id AND ended_by_admin_id IS NULL) OR "
            "(status = 'revoked' AND ended_at IS NOT NULL AND ended_by_user_id IS NULL "
            "AND ended_by_admin_id IS NOT NULL AND end_reason IS NOT NULL)",
            name="ck_resident_binding_status",
        ),
        CheckConstraint(
            "row_version > 0 AND (end_reason IS NULL OR "
            "(end_reason <> '' AND end_reason = btrim(end_reason))) AND "
            "(ended_at IS NULL OR ended_at >= granted_at)",
            name="ck_resident_binding_details",
        ),
        Index(
            "uq_resident_binding_active",
            "user_id",
            "house_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
        Index("ix_resident_binding_user_time", "user_id", "status", "created_at", "id"),
        Index(
            "ix_resident_binding_company_time",
            "property_company_id",
            "community_id",
            "status",
            "created_at",
            "id",
        ),
        Index("ix_resident_binding_house_time", "house_id", "created_at", "id"),
        Index(
            "ix_resident_binding_origin",
            "property_company_id",
            "community_id",
            "house_id",
            "user_id",
            "claim_application_id",
        ),
        Index("ix_resident_binding_admin", "property_company_id", "ended_by_admin_id"),
        Index("ix_resident_binding_ender", "ended_by_user_id"),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    property_company_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    community_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    house_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    claim_application_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    granted_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(UTC_TIMESTAMP)
    ended_by_user_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    ended_by_admin_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    end_reason: Mapped[str | None] = mapped_column(String(1000))
    row_version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False, default=utc_now)
