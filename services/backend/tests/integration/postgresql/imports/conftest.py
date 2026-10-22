import os
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from tests.support.imports.data import ImportSetup, provision_imports


@pytest.fixture
def import_setup(migrated_database_url: str) -> Iterator[ImportSetup]:
    if os.environ.get("APP_RUN_POSTGRESQL_TESTS") != "1":
        pytest.skip("Set APP_RUN_POSTGRESQL_TESTS=1 for isolated PostgreSQL imports tests")
    engine = create_engine(
        migrated_database_url,
        hide_parameters=True,
        connect_args={"options": "-c timezone=UTC -c lock_timeout=3000 -c statement_timeout=10000"},
    )
    try:
        yield provision_imports(sessionmaker(engine, autoflush=False, expire_on_commit=False))
    finally:
        engine.dispose()
