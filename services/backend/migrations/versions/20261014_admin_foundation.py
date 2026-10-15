"""Add shared admin accounts, roles, grants and audit logs."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261014_admin_foundation"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uuid_type = postgresql.UUID(as_uuid=False)
    op.create_table(
        "admin_accounts",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("scope", sa.String(32), nullable=False),
        sa.Column(
            "login_name",
            sa.String(64, collation="C"),
            nullable=False,
        ),
        sa.Column("display_name", sa.String(80), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("must_change_password", sa.Boolean(), nullable=False),
        sa.Column("session_version", sa.Integer(), nullable=False),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True, precision=6), nullable=False),
        sa.UniqueConstraint("scope", "login_name", name="uq_admin_account_login"),
        sa.CheckConstraint("login_name = lower(login_name)", name="ck_admin_account_login_lower"),
        sa.UniqueConstraint("scope", "id", name="uq_admin_account_scope_id"),
        sa.CheckConstraint(
            "scope IN ('platform_admin', 'property_admin')", name="ck_admin_account_scope"
        ),
    )
    op.create_table(
        "admin_roles",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("scope", sa.String(32), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("is_system", sa.Boolean(), nullable=False),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True, precision=6), nullable=False),
        sa.UniqueConstraint("scope", "code", name="uq_admin_role_code"),
        sa.UniqueConstraint("scope", "id", name="uq_admin_role_scope_id"),
        sa.CheckConstraint(
            "scope IN ('platform_admin', 'property_admin')", name="ck_admin_role_scope"
        ),
    )
    op.create_table(
        "admin_account_roles",
        sa.Column("scope", sa.String(32), primary_key=True),
        sa.Column("account_id", uuid_type, primary_key=True),
        sa.Column("role_id", uuid_type, primary_key=True),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True, precision=6), nullable=False),
        sa.ForeignKeyConstraint(
            ["scope", "account_id"],
            ["admin_accounts.scope", "admin_accounts.id"],
            name="fk_admin_link_account",
        ),
        sa.ForeignKeyConstraint(
            ["scope", "role_id"], ["admin_roles.scope", "admin_roles.id"], name="fk_admin_link_role"
        ),
    )
    op.create_index("ix_admin_link_scope_role", "admin_account_roles", ["scope", "role_id"])
    op.create_table(
        "admin_role_permissions",
        sa.Column("scope", sa.String(32), primary_key=True),
        sa.Column("role_id", uuid_type, primary_key=True),
        sa.Column("permission", sa.String(100), primary_key=True),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True, precision=6), nullable=False),
        sa.ForeignKeyConstraint(
            ["scope", "role_id"],
            ["admin_roles.scope", "admin_roles.id"],
            name="fk_admin_permission_role",
        ),
    )
    op.create_table(
        "admin_audit_logs",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("scope", sa.String(32), nullable=False),
        sa.Column("actor_id", uuid_type),
        sa.Column("actor_name", sa.String(80)),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("target_type", sa.String(32), nullable=False),
        sa.Column("target_id", uuid_type),
        sa.Column("result", sa.String(16), nullable=False),
        sa.Column("request_id", sa.String(64), nullable=False),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True, precision=6), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), nullable=False),
    )
    op.create_index("ix_admin_audit_scope_time", "admin_audit_logs", ["scope", "created_at", "id"])
    op.create_index("ix_admin_audit_request", "admin_audit_logs", ["scope", "request_id"])


def downgrade() -> None:
    op.drop_table("admin_audit_logs")
    op.drop_table("admin_role_permissions")
    op.drop_table("admin_account_roles")
    op.drop_table("admin_roles")
    op.drop_table("admin_accounts")
