from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
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


def utc_now() -> datetime:
    return datetime.now(UTC)


class AdminAccount(Base):
    __tablename__ = "admin_accounts"
    __table_args__ = (
        UniqueConstraint("scope", "login_name", name="uq_admin_account_login"),
        CheckConstraint("login_name = lower(login_name)", name="ck_admin_account_login_lower"),
        UniqueConstraint("scope", "id", name="uq_admin_account_scope_id"),
        UniqueConstraint("property_company_id", "id", name="uq_admin_account_company_id"),
        ForeignKeyConstraint(
            ["property_company_id"], ["property_companies.id"], name="fk_admin_account_company"
        ),
        CheckConstraint(
            "(scope = 'platform_admin' AND property_company_id IS NULL) OR "
            "(scope = 'property_admin' AND property_company_id IS NOT NULL)",
            name="ck_admin_account_company",
        ),
        Index("ix_admin_account_company_time", "property_company_id", "created_at", "id"),
        CheckConstraint(
            "scope IN ('platform_admin', 'property_admin')", name="ck_admin_account_scope"
        ),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_id)
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    property_company_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    login_name: Mapped[str] = mapped_column(String(64, collation="C"), nullable=False)
    display_name: Mapped[str] = mapped_column(String(80), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    session_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False, default=utc_now)


class AdminRole(Base):
    __tablename__ = "admin_roles"
    __table_args__ = (
        UniqueConstraint(
            "property_company_id",
            "code",
            name="uq_admin_role_company_code",
            postgresql_nulls_not_distinct=True,
        ),
        UniqueConstraint("scope", "id", name="uq_admin_role_scope_id"),
        UniqueConstraint("property_company_id", "id", name="uq_admin_role_company_id"),
        ForeignKeyConstraint(
            ["property_company_id"], ["property_companies.id"], name="fk_admin_role_company"
        ),
        CheckConstraint(
            "(scope = 'platform_admin' AND property_company_id IS NULL) OR "
            "(scope = 'property_admin' AND property_company_id IS NOT NULL)",
            name="ck_admin_role_company",
        ),
        CheckConstraint(
            "scope IN ('platform_admin', 'property_admin')", name="ck_admin_role_scope"
        ),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_id)
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    property_company_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False, default=utc_now)


class AdminAccountRole(Base):
    __tablename__ = "admin_account_roles"
    __table_args__ = (
        Index("ix_admin_link_scope_role", "scope", "role_id"),
        Index("ix_admin_link_company_account", "property_company_id", "account_id"),
        Index("ix_admin_link_company_role", "property_company_id", "role_id"),
        ForeignKeyConstraint(
            ["scope", "account_id"],
            ["admin_accounts.scope", "admin_accounts.id"],
            name="fk_admin_link_account",
        ),
        ForeignKeyConstraint(
            ["scope", "role_id"], ["admin_roles.scope", "admin_roles.id"], name="fk_admin_link_role"
        ),
        ForeignKeyConstraint(
            ["property_company_id", "account_id"],
            ["admin_accounts.property_company_id", "admin_accounts.id"],
            name="fk_admin_link_company_account",
        ),
        ForeignKeyConstraint(
            ["property_company_id", "role_id"],
            ["admin_roles.property_company_id", "admin_roles.id"],
            name="fk_admin_link_company_role",
        ),
        CheckConstraint(
            "(scope = 'platform_admin' AND property_company_id IS NULL) OR "
            "(scope = 'property_admin' AND property_company_id IS NOT NULL)",
            name="ck_admin_link_company",
        ),
    )
    scope: Mapped[str] = mapped_column(String(32), primary_key=True)
    account_id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    role_id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    property_company_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    created_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False, default=utc_now)


class AdminRolePermission(Base):
    __tablename__ = "admin_role_permissions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["scope", "role_id"],
            ["admin_roles.scope", "admin_roles.id"],
            name="fk_admin_permission_role",
        ),
    )
    scope: Mapped[str] = mapped_column(String(32), primary_key=True)
    role_id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    permission: Mapped[str] = mapped_column(String(100), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False, default=utc_now)


class AdminAuditLog(Base):
    __tablename__ = "admin_audit_logs"
    __table_args__ = (
        Index("ix_admin_audit_scope_time", "scope", "created_at", "id"),
        Index("ix_admin_audit_request", "scope", "request_id"),
        Index("ix_admin_audit_company", "property_company_id"),
        Index("ix_admin_audit_company_time", "scope", "property_company_id", "created_at", "id"),
        ForeignKeyConstraint(
            ["property_company_id"], ["property_companies.id"], name="fk_admin_audit_company"
        ),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_id)
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    property_company_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    actor_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    actor_name: Mapped[str | None] = mapped_column(String(80))
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    result: Mapped[str] = mapped_column(String(16), nullable=False)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False, default=utc_now)
    safe_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )
