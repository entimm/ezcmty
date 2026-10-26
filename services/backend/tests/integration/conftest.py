from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from pytest import MonkeyPatch, TempPathFactory
from tests.support.paths import BACKEND_ROOT
from tests.support.postgresql import (
    migrated_database_template,
    postgresql_server,
    temporary_database,
)

from backend_app.core.config import get_settings


@pytest.fixture(scope="session")
def postgresql_url(tmp_path_factory: TempPathFactory) -> Iterator[str]:
    with postgresql_server(tmp_path_factory.mktemp("postgresql")) as url:
        yield url


@pytest.fixture
def database_url(postgresql_url: str, monkeypatch: MonkeyPatch) -> Iterator[str]:
    with temporary_database(postgresql_url) as url:
        monkeypatch.setenv("APP_DATABASE_URL", url)
        get_settings.cache_clear()
        yield url


@pytest.fixture
def fresh_migrated_database_url(database_url: str) -> str:
    command.upgrade(Config(str(BACKEND_ROOT / "alembic.ini")), "head")
    return database_url


@pytest.fixture
def migrated_database_url(
    postgresql_url: str, database_template: str, monkeypatch: MonkeyPatch
) -> Iterator[str]:
    with temporary_database(postgresql_url, template=database_template) as url:
        monkeypatch.setenv("APP_DATABASE_URL", url)
        get_settings.cache_clear()
        yield url


@pytest.fixture(scope="session")
def database_template(postgresql_url: str) -> Iterator[str]:
    with migrated_database_template(postgresql_url) as name:
        yield name
