from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from devtools import reset_database
from pytest import MonkeyPatch
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from tests.support.paths import BACKEND_ROOT

from backend_app.core.config import get_settings


@pytest.fixture
def reset_database_url(database_url: str, monkeypatch: MonkeyPatch, tmp_path: Path) -> str:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("APP_IMPORT_STORAGE_ROOT", str(tmp_path / "private-imports"))
    get_settings.cache_clear()
    return database_url


@pytest.fixture
def database_owner_url(reset_database_url: str, monkeypatch: MonkeyPatch) -> Iterator[str]:
    url = make_url(reset_database_url)
    role = "reset_owner_" + uuid4().hex
    engine = create_engine(url)
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'CREATE ROLE "{role}" LOGIN NOSUPERUSER NOCREATEDB')
            connection.exec_driver_sql(f'ALTER DATABASE "{url.database}" OWNER TO "{role}"')
        owner_url = url.set(username=role).render_as_string(hide_password=False)
        monkeypatch.setenv("APP_DATABASE_URL", owner_url)
        get_settings.cache_clear()
        try:
            yield owner_url
        finally:
            with engine.begin() as connection:
                connection.exec_driver_sql(f'REASSIGN OWNED BY "{role}" TO "{url.username}"')
                connection.exec_driver_sql(f'DROP OWNED BY "{role}"')
                connection.exec_driver_sql(f'DROP ROLE "{role}"')
    finally:
        engine.dispose()


def create_probe(database_url: str) -> None:
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("CREATE TABLE public.reset_probe (value integer)")
            connection.exec_driver_sql("INSERT INTO public.reset_probe VALUES (42)")
    finally:
        engine.dispose()


def assert_probe_intact(database_url: str) -> None:
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            assert connection.exec_driver_sql("SELECT value FROM public.reset_probe").scalar() == 42
    finally:
        engine.dispose()


def test_database_owner_without_createdb_can_reset_twice_and_migrate_again(
    database_owner_url: str, monkeypatch: MonkeyPatch
) -> None:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    command.upgrade(config, "head")
    create_probe(database_owner_url)
    database = make_url(database_owner_url).database
    assert database is not None
    engine = create_engine(database_owner_url)
    try:
        with engine.connect() as connection:
            assert connection.exec_driver_sql(
                "SELECT rolsuper, rolcreatedb FROM pg_roles WHERE rolname = current_user"
            ).one() == (False, False)
            assert connection.exec_driver_sql(
                "SELECT to_regprocedure('public.billing_immutable()') IS NOT NULL"
            ).scalar()

        def confirm(_: str) -> str:
            with engine.connect() as observer:
                assert (
                    observer.exec_driver_sql(
                        "SELECT count(*) FROM pg_stat_activity WHERE usename = current_user "
                        "AND state IN ('idle in transaction', 'idle in transaction (aborted)')"
                    ).scalar()
                    == 0
                )
            return database

        monkeypatch.setattr("builtins.input", confirm)
        assert reset_database.main([]) == 0
        assert reset_database.main([]) == 0
        with engine.connect() as connection:
            assert (
                connection.exec_driver_sql(
                    "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = 'public'"
                ).scalar()
                == 0
            )
            assert (
                connection.exec_driver_sql(
                    "SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
                    "WHERE n.nspname = 'public'"
                ).scalar()
                == 0
            )
            assert connection.exec_driver_sql(
                "SELECT to_regclass('public.alembic_version') IS NULL"
            ).scalar()
            assert (
                connection.exec_driver_sql(
                    "SELECT nspowner::regrole::text FROM pg_namespace WHERE nspname = 'public'"
                ).scalar()
                == "pg_database_owner"
            )
            assert connection.exec_driver_sql(
                "SELECT EXISTS (SELECT 1 FROM pg_namespace n, aclexplode(n.nspacl) a "
                "WHERE n.nspname = 'public' AND a.grantee = 0 AND a.privilege_type = 'USAGE')"
            ).scalar()
        command.upgrade(config, "head")
        with engine.connect() as connection:
            assert (
                connection.exec_driver_sql(
                    "SELECT version_num FROM public.alembic_version"
                ).scalar()
                == ScriptDirectory.from_config(config).get_current_head()
            )
            assert connection.exec_driver_sql(
                "SELECT to_regprocedure('public.billing_immutable()') IS NOT NULL"
            ).scalar()
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    ("reply", "exit_code"),
    [("wrong-database", 1), (EOFError, 1), (KeyboardInterrupt, 130)],
    ids=["wrong-name", "eof", "interrupt"],
)
def test_cancelled_confirmation_preserves_data(
    reset_database_url: str,
    monkeypatch: MonkeyPatch,
    reply: str | type[BaseException],
    exit_code: int,
) -> None:
    create_probe(reset_database_url)

    def confirm(_: str) -> str:
        if isinstance(reply, str):
            return reply
        raise reply

    monkeypatch.setattr("builtins.input", confirm)
    assert reset_database.main([]) == exit_code
    assert_probe_intact(reset_database_url)


@pytest.mark.parametrize("environment", ["production", "staging", None])
def test_unsafe_or_implicit_environment_preserves_data(
    reset_database_url: str, monkeypatch: MonkeyPatch, environment: str | None
) -> None:
    create_probe(reset_database_url)
    if environment is None:
        monkeypatch.delenv("APP_ENV")
    else:
        monkeypatch.setenv("APP_ENV", environment)
    monkeypatch.setenv("APP_ADMIN_TRUSTED_ORIGINS", '["https://platform.example.test"]')
    get_settings.cache_clear()

    def unexpected_confirmation(_: str) -> str:
        pytest.fail("Environment rejection must happen before confirmation")

    monkeypatch.setattr("builtins.input", unexpected_confirmation)
    assert reset_database.main([]) == 1
    assert_probe_intact(reset_database_url)


def test_schema_creation_permission_failure_rolls_back_dropped_data(
    database_owner_url: str, reset_database_url: str, monkeypatch: MonkeyPatch
) -> None:
    url = make_url(reset_database_url)
    owner = make_url(database_owner_url).username
    create_probe(database_owner_url)
    engine = create_engine(reset_database_url)
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'ALTER DATABASE "{url.database}" OWNER TO "{url.username}"')
            connection.exec_driver_sql(f'ALTER SCHEMA public OWNER TO "{owner}"')
            connection.exec_driver_sql(f'REVOKE CREATE ON DATABASE "{url.database}" FROM PUBLIC')
        monkeypatch.setattr("builtins.input", lambda _: url.database)
        assert reset_database.main([]) == 1
        assert_probe_intact(database_owner_url)
    finally:
        engine.dispose()
