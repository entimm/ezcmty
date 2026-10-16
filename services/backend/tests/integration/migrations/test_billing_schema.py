from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import CHAR, VARCHAR
from tests.support.paths import BACKEND_ROOT

from backend_app.db.base import Base
from backend_app.db.session import get_engine


def test_billing_text_lengths_match_approved_limits(migrated_database_url: str) -> None:
    with get_engine().connect() as connection:
        inspector = inspect(connection)
        for table, limits in {
            "bills": {
                "house_label_snapshot": 512,
                "manual_amount_reason": 1000,
                "void_reason": 1000,
            },
            "property_fee_basis_versions": {"change_reason": 1000},
            "bill_operations": {"reason": 1000},
        }.items():
            columns = {c["name"]: c for c in inspector.get_columns(table)}
            for name, length in limits.items():
                column_type = columns[name]["type"]
                assert isinstance(column_type, VARCHAR)
                assert column_type.length == length
        operations = {c["name"]: c for c in inspector.get_columns("bill_operations")}
        fingerprint_type = operations["request_fingerprint"]["type"]
        assert isinstance(fingerprint_type, CHAR)
        assert fingerprint_type.length == 64


def test_empty_billing_schema_downgrades_and_upgrades_cleanly(migrated_database_url: str) -> None:
    cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
    command.downgrade(cfg, "20261015_property_housing")
    with get_engine().connect() as connection:
        assert "bills" not in inspect(connection).get_table_names()
    command.upgrade(cfg, "head")
    with get_engine().connect() as connection:
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
