from datetime import datetime

from sqlalchemy import (
    CHAR,
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    true,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend_app.core.identifiers import new_id
from backend_app.db.base import Base
from backend_app.db.types import UTC_TIMESTAMP
from backend_app.models.admin import utc_now


class MiniappUser(Base):
    __tablename__ = "miniapp_users"
    __table_args__ = (
        UniqueConstraint("wechat_openid", name="uq_miniapp_user_openid"),
        CheckConstraint(
            "wechat_openid <> '' AND wechat_openid = btrim(wechat_openid)",
            name="ck_miniapp_user_openid",
        ),
        CheckConstraint("session_version > 0", name="ck_miniapp_user_version"),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_id)
    wechat_openid: Mapped[str] = mapped_column(String(128, collation="C"), nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )
    session_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    last_login_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False, default=utc_now)
    created_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False, default=utc_now)


class PhoneBinding(Base):
    __tablename__ = "miniapp_phone_bindings"
    __table_args__ = (
        ForeignKeyConstraint(["user_id"], ["miniapp_users.id"], name="fk_phone_binding_user"),
        UniqueConstraint("user_id", "phone", name="uq_phone_binding_number"),
        UniqueConstraint("user_id", "id", name="uq_phone_binding_user_id"),
        CheckConstraint("phone ~ '^1[3-9][0-9]{9}$'", name="ck_phone_binding_number"),
        CheckConstraint(
            "(status = 'active' AND unbound_at IS NULL) OR "
            "(status = 'unbound' AND unbound_at IS NOT NULL)",
            name="ck_phone_binding_status",
        ),
        CheckConstraint(
            "row_version > 0 AND first_verified_at <= last_verified_at",
            name="ck_phone_binding_version_time",
        ),
        Index("ix_phone_binding_user_time", "user_id", "status", "created_at", "id"),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    phone: Mapped[str] = mapped_column(String(11), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    first_verified_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False)
    last_verified_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False)
    unbound_at: Mapped[datetime | None] = mapped_column(UTC_TIMESTAMP)
    row_version: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=1, server_default="1"
    )
    created_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False, default=utc_now)


class PhoneVerification(Base):
    __tablename__ = "miniapp_phone_verifications"
    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id", "phone_binding_id"],
            ["miniapp_phone_bindings.user_id", "miniapp_phone_bindings.id"],
            name="fk_phone_verification_binding",
        ),
        UniqueConstraint("user_id", "idempotency_key", name="uq_phone_verification_key"),
        UniqueConstraint("user_id", "wechat_code_hash", name="uq_phone_verification_code"),
        CheckConstraint("method = 'wechat_fast'", name="ck_phone_verification_method"),
        CheckConstraint(
            "idempotency_key ~ '^[A-Za-z0-9_-]{1,128}$' AND "
            "request_fingerprint ~ '^[0-9a-f]{64}$' AND wechat_code_hash ~ '^[0-9a-f]{64}$'",
            name="ck_phone_verification_keys",
        ),
        Index("ix_phone_verification_binding_time", "phone_binding_id", "verified_at", "id"),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    phone_binding_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    method: Mapped[str] = mapped_column(String(32), nullable=False, default="wechat_fast")
    wechat_code_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    wechat_authorized_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False)
    verified_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False, default=utc_now)
