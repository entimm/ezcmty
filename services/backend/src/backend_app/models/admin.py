from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend_app.db.base import Base


def new_id() -> str:
    return str(uuid4())


def utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class AdminAccount(Base):
    __tablename__ = "admin_accounts"
    __table_args__ = (
        UniqueConstraint("scope", "login_name", name="uq_admin_account_login"),
        UniqueConstraint("scope", "id", name="uq_admin_account_scope_id"),
        CheckConstraint(
            "scope IN ('platform_admin', 'property_admin')", name="ck_admin_account_scope"
        ),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    login_name: Mapped[str] = mapped_column(
        String(64, collation="utf8mb4_bin").with_variant(String(64), "sqlite"), nullable=False
    )
    display_name: Mapped[str] = mapped_column(String(80), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    session_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)


class AdminRole(Base):
    __tablename__ = "admin_roles"
    __table_args__ = (
        UniqueConstraint("scope", "code", name="uq_admin_role_code"),
        UniqueConstraint("scope", "id", name="uq_admin_role_scope_id"),
        CheckConstraint(
            "scope IN ('platform_admin', 'property_admin')", name="ck_admin_role_scope"
        ),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class AdminAccountRole(Base):
    __tablename__ = "admin_account_roles"
    __table_args__ = (
        ForeignKeyConstraint(
            ["scope", "account_id"],
            ["admin_accounts.scope", "admin_accounts.id"],
            name="fk_admin_link_account",
        ),
        ForeignKeyConstraint(
            ["scope", "role_id"], ["admin_roles.scope", "admin_roles.id"], name="fk_admin_link_role"
        ),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )
    scope: Mapped[str] = mapped_column(String(32), primary_key=True)
    account_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    role_id: Mapped[str] = mapped_column(String(36), primary_key=True)


class AdminRolePermission(Base):
    __tablename__ = "admin_role_permissions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["scope", "role_id"],
            ["admin_roles.scope", "admin_roles.id"],
            name="fk_admin_permission_role",
        ),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )
    scope: Mapped[str] = mapped_column(String(32), primary_key=True)
    role_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    permission: Mapped[str] = mapped_column(String(100), primary_key=True)


class AdminAuditLog(Base):
    __tablename__ = "admin_audit_logs"
    __table_args__ = (
        Index("ix_admin_audit_scope_time", "scope", "created_at", "id"),
        Index("ix_admin_audit_request", "scope", "request_id"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(36))
    actor_name: Mapped[str | None] = mapped_column(String(80))
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[str | None] = mapped_column(String(36))
    result: Mapped[str] = mapped_column(String(16), nullable=False)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)
    safe_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, nullable=False, default=dict
    )
