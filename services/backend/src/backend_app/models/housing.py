from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    Integer,
    SmallInteger,
    String,
    UniqueConstraint,
    text,
    true,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend_app.core.identifiers import new_id
from backend_app.db.base import Base
from backend_app.db.types import UTC_TIMESTAMP
from backend_app.models.admin import utc_now


class SpaceNode(Base):
    __tablename__ = "community_space_nodes"
    __table_args__ = (
        UniqueConstraint("community_id", "id", name="uq_space_node_community_id"),
        UniqueConstraint(
            "community_id",
            "parent_id",
            "name",
            name="uq_space_node_sibling_name",
            postgresql_nulls_not_distinct=True,
        ),
        ForeignKeyConstraint(["community_id"], ["communities.id"], name="fk_space_node_community"),
        ForeignKeyConstraint(
            ["community_id", "parent_id"],
            ["community_space_nodes.community_id", "community_space_nodes.id"],
            name="fk_space_node_parent",
        ),
        CheckConstraint("node_type IN ('phase', 'building', 'unit')", name="ck_space_node_type"),
        CheckConstraint("parent_id IS NULL OR parent_id <> id", name="ck_space_node_parent"),
        CheckConstraint("sort_order >= 0", name="ck_space_node_sort"),
        CheckConstraint("name <> '' AND name = btrim(name)", name="ck_space_node_name"),
        CheckConstraint(
            "external_code IS NULL OR "
            "(external_code <> '' AND external_code = btrim(external_code))",
            name="ck_space_node_external",
        ),
        Index("ix_space_node_parent", "community_id", "parent_id", "sort_order", "id"),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_id)
    community_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    parent_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    node_type: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    external_code: Mapped[str | None] = mapped_column(String(64))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )
    created_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False, default=utc_now)


class House(Base):
    __tablename__ = "houses"
    __table_args__ = (
        ForeignKeyConstraint(["community_id"], ["communities.id"], name="fk_house_community"),
        ForeignKeyConstraint(
            ["community_id", "space_node_id"],
            ["community_space_nodes.community_id", "community_space_nodes.id"],
            name="fk_house_space_node",
        ),
        UniqueConstraint("space_node_id", "room_no", name="uq_house_room_no"),
        CheckConstraint("room_no <> '' AND room_no = btrim(room_no)", name="ck_house_room_no"),
        CheckConstraint(
            "external_code IS NULL OR "
            "(external_code <> '' AND external_code = btrim(external_code))",
            name="ck_house_external",
        ),
        Index("ix_house_community_time", "community_id", "created_at", "id"),
        Index("ix_house_node_time", "community_id", "space_node_id", "created_at", "id"),
        Index("ix_house_room_time", "community_id", "room_no", "created_at", "id"),
        Index(
            "ix_house_community_external",
            "community_id",
            "external_code",
            "created_at",
            "id",
            postgresql_where=text("external_code IS NOT NULL"),
        ),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_id)
    community_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    space_node_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    room_no: Mapped[str] = mapped_column(String(32), nullable=False)
    floor_no: Mapped[int | None] = mapped_column(SmallInteger)
    external_code: Mapped[str | None] = mapped_column(String(64))
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )
    created_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False, default=utc_now)


class HouseOwner(Base):
    __tablename__ = "house_owners"
    __table_args__ = (
        ForeignKeyConstraint(["house_id"], ["houses.id"], name="fk_house_owner_house"),
        UniqueConstraint("house_id", "name", "phone", name="uq_house_owner_contact"),
        CheckConstraint("name <> '' AND name = btrim(name)", name="ck_house_owner_name"),
        CheckConstraint("phone ~ '^1[3-9][0-9]{9}$'", name="ck_house_owner_phone"),
        Index("ix_house_owner_time", "house_id", "created_at", "id"),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_id)
    house_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    phone: Mapped[str] = mapped_column(String(32), nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )
    created_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False, default=utc_now)
