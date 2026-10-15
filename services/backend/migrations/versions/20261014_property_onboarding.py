"""Add property organizations and enforce company ownership of property identities."""

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import postgresql

revision = "20261014_property_onboarding"
down_revision = "20261014_admin_foundation"
branch_labels = None
depends_on = None

_uuid = postgresql.UUID(as_uuid=False)
_time = postgresql.TIMESTAMP(timezone=True, precision=6)
_ownership = (
    "(scope = 'platform_admin' AND property_company_id IS NULL) OR "
    "(scope = 'property_admin' AND property_company_id IS NOT NULL)"
)


def _preflight(*, downgrade: bool = False) -> None:
    if context.is_offline_mode():
        raise RuntimeError("Property ownership migration requires an online preflight")
    connection = op.get_bind()
    for table in ("admin_accounts", "admin_roles", "admin_account_roles"):
        count = connection.scalar(
            sa.text(f"SELECT COUNT(*) FROM {table} WHERE scope = 'property_admin'")
        )
        if count:
            raise RuntimeError(
                "Property identities exist; confirm their company mapping before migration"
                if not downgrade
                else "Cannot downgrade while property identities exist"
            )
    if downgrade:
        for table in ("communities", "property_companies"):
            if connection.scalar(sa.text(f"SELECT COUNT(*) FROM {table}")):
                raise RuntimeError("Cannot downgrade while property organization data exists")


def upgrade() -> None:
    _preflight()
    op.create_table(
        "property_companies",
        sa.Column("id", _uuid, primary_key=True),
        sa.Column("code", sa.String(64, collation="C"), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("contact_name", sa.String(80)),
        sa.Column("contact_phone", sa.String(32)),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", _time, nullable=False),
        sa.Column("updated_at", _time, nullable=False),
        sa.UniqueConstraint("code", name="uq_property_company_code"),
        sa.CheckConstraint("code = upper(code)", name="ck_property_company_code_upper"),
    )
    op.create_index("ix_property_company_time", "property_companies", ["created_at", "id"])
    op.create_table(
        "communities",
        sa.Column("id", _uuid, primary_key=True),
        sa.Column("property_company_id", _uuid, nullable=False),
        sa.Column("code", sa.String(64, collation="C"), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("address", sa.String(255), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", _time, nullable=False),
        sa.Column("updated_at", _time, nullable=False),
        sa.UniqueConstraint("code", name="uq_community_code"),
        sa.ForeignKeyConstraint(
            ["property_company_id"], ["property_companies.id"], name="fk_community_company"
        ),
        sa.CheckConstraint("code = upper(code)", name="ck_community_code_upper"),
    )
    op.create_index("ix_community_time", "communities", ["created_at", "id"])
    op.create_index(
        "ix_community_company_time", "communities", ["property_company_id", "created_at", "id"]
    )
    with op.batch_alter_table("admin_accounts") as batch:
        batch.add_column(sa.Column("property_company_id", _uuid))
        batch.create_unique_constraint("uq_admin_account_company_id", ["property_company_id", "id"])
        batch.create_foreign_key(
            "fk_admin_account_company", "property_companies", ["property_company_id"], ["id"]
        )
        batch.create_check_constraint("ck_admin_account_company", _ownership)
        batch.create_index(
            "ix_admin_account_company_time", ["property_company_id", "created_at", "id"]
        )
    with op.batch_alter_table("admin_roles") as batch:
        batch.add_column(sa.Column("property_company_id", _uuid))
        batch.create_unique_constraint("uq_admin_role_company_id", ["property_company_id", "id"])
        batch.create_unique_constraint(
            "uq_admin_role_company_code",
            ["property_company_id", "code"],
            postgresql_nulls_not_distinct=True,
        )
        batch.drop_constraint("uq_admin_role_code", type_="unique")
        batch.create_foreign_key(
            "fk_admin_role_company", "property_companies", ["property_company_id"], ["id"]
        )
        batch.create_check_constraint("ck_admin_role_company", _ownership)
    with op.batch_alter_table("admin_account_roles") as batch:
        batch.add_column(sa.Column("property_company_id", _uuid))
        batch.create_check_constraint("ck_admin_link_company", _ownership)
        batch.create_index("ix_admin_link_company_account", ["property_company_id", "account_id"])
        batch.create_index("ix_admin_link_company_role", ["property_company_id", "role_id"])
        batch.create_foreign_key(
            "fk_admin_link_company_account",
            "admin_accounts",
            ["property_company_id", "account_id"],
            ["property_company_id", "id"],
        )
        batch.create_foreign_key(
            "fk_admin_link_company_role",
            "admin_roles",
            ["property_company_id", "role_id"],
            ["property_company_id", "id"],
        )


def downgrade() -> None:
    _preflight(downgrade=True)
    with op.batch_alter_table("admin_account_roles") as batch:
        batch.drop_constraint("fk_admin_link_company_account", type_="foreignkey")
        batch.drop_constraint("fk_admin_link_company_role", type_="foreignkey")
        batch.drop_constraint("ck_admin_link_company", type_="check")
        batch.drop_index("ix_admin_link_company_account")
        batch.drop_index("ix_admin_link_company_role")
        batch.drop_column("property_company_id")
    with op.batch_alter_table("admin_roles") as batch:
        batch.drop_constraint("ck_admin_role_company", type_="check")
        batch.drop_constraint("fk_admin_role_company", type_="foreignkey")
        batch.drop_constraint("uq_admin_role_company_id", type_="unique")
        batch.drop_constraint("uq_admin_role_company_code", type_="unique")
        batch.create_unique_constraint("uq_admin_role_code", ["scope", "code"])
        batch.drop_column("property_company_id")
    with op.batch_alter_table("admin_accounts") as batch:
        batch.drop_constraint("ck_admin_account_company", type_="check")
        batch.drop_constraint("fk_admin_account_company", type_="foreignkey")
        batch.drop_constraint("uq_admin_account_company_id", type_="unique")
        batch.drop_index("ix_admin_account_company_time")
        batch.drop_column("property_company_id")
    op.drop_table("communities")
    op.drop_table("property_companies")
