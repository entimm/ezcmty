"""Audit log company ownership."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261014_admin_audit_company"
down_revision = "20261014_property_onboarding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uuid_type = postgresql.UUID(as_uuid=False)
    with op.batch_alter_table("admin_audit_logs") as batch:
        batch.add_column(sa.Column("property_company_id", uuid_type, nullable=True))
        batch.create_foreign_key(
            "fk_admin_audit_company", "property_companies", ["property_company_id"], ["id"]
        )
        batch.create_index("ix_admin_audit_company", ["property_company_id"])
        batch.create_index(
            "ix_admin_audit_company_time", ["scope", "property_company_id", "created_at", "id"]
        )


def downgrade() -> None:
    if op.get_bind().scalar(
        sa.text("SELECT COUNT(*) FROM admin_audit_logs WHERE property_company_id IS NOT NULL")
    ):
        raise RuntimeError("Cannot remove company ownership from existing audit records")
    with op.batch_alter_table("admin_audit_logs") as batch:
        batch.drop_index("ix_admin_audit_company_time")
        batch.drop_index("ix_admin_audit_company")
        batch.drop_constraint("fk_admin_audit_company", type_="foreignkey")
        batch.drop_column("property_company_id")
