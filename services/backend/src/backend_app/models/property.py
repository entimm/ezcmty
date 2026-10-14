from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import Mapped, mapped_column

from backend_app.core.identifiers import new_id
from backend_app.db.base import Base
from backend_app.db.types import UUIDBinary
from backend_app.models.admin import utc_now

_timestamp = DateTime().with_variant(DATETIME(fsp=6), "mysql")


class PropertyCompany(Base):
    __tablename__ = "property_companies"
    __table_args__ = (
        UniqueConstraint("code", name="uq_property_company_code"),
        CheckConstraint("enabled IN (0, 1)", name="ck_property_company_enabled"),
        Index("ix_property_company_time", "created_at", "id"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )
    id: Mapped[str] = mapped_column(UUIDBinary(), primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    contact_name: Mapped[str | None] = mapped_column(String(80))
    contact_phone: Mapped[str | None] = mapped_column(String(32))
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(_timestamp, nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(_timestamp, nullable=False, default=utc_now)


class Community(Base):
    __tablename__ = "communities"
    __table_args__ = (
        UniqueConstraint("code", name="uq_community_code"),
        ForeignKeyConstraint(
            ["property_company_id"], ["property_companies.id"], name="fk_community_company"
        ),
        CheckConstraint("enabled IN (0, 1)", name="ck_community_enabled"),
        Index("ix_community_time", "created_at", "id"),
        Index("ix_community_company_time", "property_company_id", "created_at", "id"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )
    id: Mapped[str] = mapped_column(UUIDBinary(), primary_key=True, default=new_id)
    property_company_id: Mapped[str] = mapped_column(UUIDBinary(), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    address: Mapped[str] = mapped_column(String(255), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    created_at: Mapped[datetime] = mapped_column(_timestamp, nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(_timestamp, nullable=False, default=utc_now)
