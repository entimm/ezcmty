"""Separate business ownership from the account that performed the operation."""

from alembic import op
from sqlalchemy import text

revision = "20261029_business_actors"
down_revision = "20261027_client_identities"
branch_labels = None
depends_on = None

ACTOR_FOREIGN_KEYS = (
    ("bill_operations", "actor_id", "fk_bill_operation_actor"),
    ("house_claim_applications", "reviewed_by_admin_id", "fk_house_claim_reviewer"),
    ("resident_house_bindings", "ended_by_admin_id", "fk_resident_binding_admin"),
)


def upgrade() -> None:
    for table, actor_column, constraint in ACTOR_FOREIGN_KEYS:
        op.drop_constraint(constraint, table, type_="foreignkey")
        op.create_foreign_key(constraint, table, "admin_accounts", [actor_column], ["id"])


def downgrade() -> None:
    connection = op.get_bind()
    # Freeze account ownership and business facts before checking compatibility.
    connection.execute(text("LOCK TABLE admin_accounts IN SHARE MODE"))
    connection.execute(
        text(
            "LOCK TABLE bill_operations, house_claim_applications, resident_house_bindings "
            "IN ACCESS EXCLUSIVE MODE"
        )
    )
    for table, actor_column, _ in ACTOR_FOREIGN_KEYS:
        incompatible = connection.scalar(
            text(
                f"SELECT EXISTS (SELECT 1 FROM {table} AS business "
                f"JOIN admin_accounts AS actor ON actor.id = business.{actor_column} "
                f"WHERE business.{actor_column} IS NOT NULL AND "
                "business.property_company_id IS DISTINCT FROM actor.property_company_id)"
            )
        )
        if incompatible:
            raise RuntimeError(
                "Cannot restore company-scoped actor foreign keys while "
                "cross-company actor history exists"
            )
    for table, actor_column, constraint in ACTOR_FOREIGN_KEYS:
        op.drop_constraint(constraint, table, type_="foreignkey")
        op.create_foreign_key(
            constraint,
            table,
            "admin_accounts",
            ["property_company_id", actor_column],
            ["property_company_id", "id"],
        )
