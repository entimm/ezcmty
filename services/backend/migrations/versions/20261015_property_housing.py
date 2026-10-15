"""Add community spaces, houses and property owner records."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261015_property_housing"
down_revision = "20261014_admin_audit_company"
branch_labels = None
depends_on = None

_uuid = postgresql.UUID(as_uuid=False)
_time = postgresql.TIMESTAMP(timezone=True, precision=6)


def _common_columns() -> list[sa.Column]:  # type: ignore[type-arg]
    return [
        sa.Column("id", _uuid, primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", _time, nullable=False),
        sa.Column("updated_at", _time, nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "community_space_nodes",
        *_common_columns(),
        sa.Column("community_id", _uuid, nullable=False),
        sa.Column("parent_id", _uuid),
        sa.Column("node_type", sa.String(16), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("external_code", sa.String(64)),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("community_id", "id", name="uq_space_node_community_id"),
        sa.UniqueConstraint(
            "community_id",
            "parent_id",
            "name",
            name="uq_space_node_sibling_name",
            postgresql_nulls_not_distinct=True,
        ),
        sa.ForeignKeyConstraint(
            ["community_id"], ["communities.id"], name="fk_space_node_community"
        ),
        sa.ForeignKeyConstraint(
            ["community_id", "parent_id"],
            ["community_space_nodes.community_id", "community_space_nodes.id"],
            name="fk_space_node_parent",
        ),
        sa.CheckConstraint("node_type IN ('phase', 'building', 'unit')", name="ck_space_node_type"),
        sa.CheckConstraint("parent_id IS NULL OR parent_id <> id", name="ck_space_node_parent"),
        sa.CheckConstraint("sort_order >= 0", name="ck_space_node_sort"),
        sa.CheckConstraint("name <> '' AND name = btrim(name)", name="ck_space_node_name"),
        sa.CheckConstraint(
            "external_code IS NULL OR "
            "(external_code <> '' AND external_code = btrim(external_code))",
            name="ck_space_node_external",
        ),
    )
    op.create_index(
        "ix_space_node_parent",
        "community_space_nodes",
        ["community_id", "parent_id", "sort_order", "id"],
    )
    op.create_table(
        "houses",
        *_common_columns(),
        sa.Column("community_id", _uuid, nullable=False),
        sa.Column("space_node_id", _uuid, nullable=False),
        sa.Column("room_no", sa.String(32), nullable=False),
        sa.Column("floor_no", sa.SmallInteger()),
        sa.Column("external_code", sa.String(64)),
        sa.ForeignKeyConstraint(["community_id"], ["communities.id"], name="fk_house_community"),
        sa.ForeignKeyConstraint(
            ["community_id", "space_node_id"],
            ["community_space_nodes.community_id", "community_space_nodes.id"],
            name="fk_house_space_node",
        ),
        sa.UniqueConstraint("space_node_id", "room_no", name="uq_house_room_no"),
        sa.CheckConstraint("room_no <> '' AND room_no = btrim(room_no)", name="ck_house_room_no"),
        sa.CheckConstraint(
            "external_code IS NULL OR "
            "(external_code <> '' AND external_code = btrim(external_code))",
            name="ck_house_external",
        ),
    )
    for name, columns in (
        ("ix_house_community_time", ["community_id", "created_at", "id"]),
        ("ix_house_node_time", ["community_id", "space_node_id", "created_at", "id"]),
        ("ix_house_room_time", ["community_id", "room_no", "created_at", "id"]),
    ):
        op.create_index(name, "houses", columns)
    op.create_index(
        "ix_house_community_external",
        "houses",
        ["community_id", "external_code", "created_at", "id"],
        postgresql_where=sa.text("external_code IS NOT NULL"),
    )
    op.create_table(
        "house_owners",
        *_common_columns(),
        sa.Column("house_id", _uuid, nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("phone", sa.String(32), nullable=False),
        sa.ForeignKeyConstraint(["house_id"], ["houses.id"], name="fk_house_owner_house"),
        sa.UniqueConstraint("house_id", "name", "phone", name="uq_house_owner_contact"),
        sa.CheckConstraint("name <> '' AND name = btrim(name)", name="ck_house_owner_name"),
        sa.CheckConstraint("phone ~ '^1[3-9][0-9]{9}$'", name="ck_house_owner_phone"),
    )
    op.create_index("ix_house_owner_time", "house_owners", ["house_id", "created_at", "id"])


def downgrade() -> None:
    connection = op.get_bind()
    for table in ("house_owners", "houses", "community_space_nodes"):
        if connection.scalar(sa.text(f"SELECT EXISTS (SELECT 1 FROM {table})")):
            raise RuntimeError("Cannot downgrade while housing data exists")
    op.drop_table("house_owners")
    op.drop_table("houses")
    op.drop_table("community_space_nodes")
