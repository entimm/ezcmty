from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect
from tests.support.paths import BACKEND_ROOT

from backend_app.db.base import Base
from backend_app.db.session import get_engine

PAYMENT_TABLES = {
    "property_merchant_bindings",
    "profit_sharing_rule_versions",
    "profit_sharing_rule_version_items",
    "payment_orders",
    "payment_order_items",
    "bill_payment_reservations",
    "profit_sharing_allocations",
    "profit_sharing_orders",
    "profit_sharing_order_items",
    "payment_unfreeze_orders",
    "payment_tasks",
    "payment_channel_requests",
    "payment_channel_notifications",
    "payment_reconciliation_runs",
    "payment_reconciliation_discrepancies",
}


def test_payment_schema_has_one_head_and_matches_models(migrated_database_url: str) -> None:
    cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
    assert len(ScriptDirectory.from_config(cfg).get_heads()) == 1
    with get_engine().connect() as connection:
        inspector = inspect(connection)
        assert PAYMENT_TABLES <= set(inspector.get_table_names())
        assert "payment_in_progress" not in {c["name"] for c in inspector.get_columns("bills")}
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []


def test_payment_schema_empty_database_round_trip(migrated_database_url: str) -> None:
    cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
    command.downgrade(cfg, "20261017_house_claims")
    with get_engine().connect() as connection:
        assert PAYMENT_TABLES.isdisjoint(inspect(connection).get_table_names())
    command.upgrade(cfg, "head")
    with get_engine().connect() as connection:
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
