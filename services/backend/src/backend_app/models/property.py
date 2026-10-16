from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    false,
    true,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend_app.core.identifiers import new_id
from backend_app.db.base import Base
from backend_app.db.types import UTC_TIMESTAMP
from backend_app.models.admin import utc_now


class PropertyCompany(Base):
    __tablename__ = "property_companies"
    __table_args__ = (
        UniqueConstraint("code", name="uq_property_company_code"),
        CheckConstraint("code = upper(code)", name="ck_property_company_code_upper"),
        Index("ix_property_company_time", "created_at", "id"),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(String(64, collation="C"), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    contact_name: Mapped[str | None] = mapped_column(String(80))
    contact_phone: Mapped[str | None] = mapped_column(String(32))
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    created_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False, default=utc_now)


class Community(Base):
    __tablename__ = "communities"
    __table_args__ = (
        UniqueConstraint("code", name="uq_community_code"),
        UniqueConstraint("property_company_id", "id", name="uq_community_company_id"),
        ForeignKeyConstraint(
            ["property_company_id"], ["property_companies.id"], name="fk_community_company"
        ),
        CheckConstraint("code = upper(code)", name="ck_community_code_upper"),
        Index("ix_community_time", "created_at", "id"),
        Index("ix_community_company_time", "property_company_id", "created_at", "id"),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_id)
    property_company_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    code: Mapped[str] = mapped_column(String(64, collation="C"), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    address: Mapped[str] = mapped_column(String(255), nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )
    created_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False, default=utc_now)
