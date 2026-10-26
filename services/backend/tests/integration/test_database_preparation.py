import os

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from pytest import MonkeyPatch
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from tests.support.paths import BACKEND_ROOT
from tests.support.postgresql import migrated_database_template, temporary_database

from backend_app.core.config import get_settings
from backend_app.models.admin import AdminAccount
from backend_app.models.property import PropertyCompany


def test_migrated_template_is_frozen_at_head_without_business_records(
    postgresql_url: str, database_template: str
) -> None:
    server = create_engine(postgresql_url + "/postgres")
    try:
        with server.connect() as connection:
            assert (
                connection.execute(
                    text("SELECT datallowconn FROM pg_database WHERE datname = :name"),
                    {"name": database_template},
                ).scalar_one()
                is False
            )
            assert (
                connection.execute(
                    text("SELECT count(*) FROM pg_stat_activity WHERE datname = :name"),
                    {"name": database_template},
                ).scalar_one()
                == 0
            )
        with temporary_database(postgresql_url, template=database_template) as url:
            engine = create_engine(url)
            try:
                with engine.connect() as connection:
                    head = ScriptDirectory.from_config(
                        Config(str(BACKEND_ROOT / "alembic.ini"))
                    ).get_current_head()
                    assert (
                        connection.execute(
                            text("SELECT version_num FROM alembic_version")
                        ).scalar_one()
                        == head
                    )
                with Session(engine) as db:
                    assert db.scalar(select(func.count()).select_from(AdminAccount)) == 0
                    assert db.scalar(select(func.count()).select_from(PropertyCompany)) == 0
            finally:
                engine.dispose()
    finally:
        server.dispose()


def test_cloned_databases_preserve_real_commits_and_rollbacks_without_sharing_data(
    postgresql_url: str, database_template: str
) -> None:
    with (
        temporary_database(postgresql_url, template=database_template) as first_url,
        temporary_database(postgresql_url, template=database_template) as second_url,
    ):
        first = create_engine(first_url)
        second = create_engine(second_url)
        try:
            with Session(first) as db:
                db.add(PropertyCompany(code="COMMITTED", name="已提交"))
                db.commit()
            with Session(first) as db:
                db.add(PropertyCompany(code="ROLLED_BACK", name="回滚"))
                db.flush()
                db.rollback()
            with Session(first) as db:
                assert db.scalars(select(PropertyCompany.code)).all() == ["COMMITTED"]
            with Session(second) as db:
                assert db.scalar(select(func.count()).select_from(PropertyCompany)) == 0
        finally:
            first.dispose()
            second.dispose()
    with temporary_database(postgresql_url, template=database_template) as fresh_url:
        fresh = create_engine(fresh_url)
        try:
            with Session(fresh) as db:
                assert db.scalar(select(func.count()).select_from(PropertyCompany)) == 0
        finally:
            fresh.dispose()


def test_failed_case_removes_clone_even_with_an_idle_pooled_connection(
    postgresql_url: str, database_template: str
) -> None:
    engine = None
    name = None
    try:
        with pytest.raises(RuntimeError, match="case failed"):
            with temporary_database(postgresql_url, template=database_template) as url:
                name = make_url(url).database
                engine = create_engine(url)
                with engine.connect() as connection:
                    assert connection.execute(text("SELECT 1")).scalar_one() == 1
                raise RuntimeError("case failed")
        server = create_engine(postgresql_url + "/postgres")
        try:
            with server.connect() as connection:
                assert (
                    connection.execute(
                        text("SELECT count(*) FROM pg_database WHERE datname = :name"),
                        {"name": name},
                    ).scalar_one()
                    == 0
                )
        finally:
            server.dispose()
    finally:
        if engine is not None:
            engine.dispose()


def test_failed_template_migration_removes_database_and_restores_environment(
    postgresql_url: str, monkeypatch: MonkeyPatch
) -> None:
    original_url = os.environ.get("APP_DATABASE_URL")
    original_environment = os.environ.get("APP_ENV")
    attempted_url = None

    def fail_upgrade(config: Config, revision: str) -> None:
        nonlocal attempted_url
        attempted_url = get_settings().database_url.get_secret_value()
        assert attempted_url.startswith(postgresql_url + "/test_")
        assert revision == "head"
        raise RuntimeError("migration failed")

    monkeypatch.setattr(command, "upgrade", fail_upgrade)
    with pytest.raises(RuntimeError, match="migration failed"):
        with migrated_database_template(postgresql_url):
            pytest.fail("failed migration must not publish a template")
    assert os.environ.get("APP_DATABASE_URL") == original_url
    assert os.environ.get("APP_ENV") == original_environment
    assert get_settings.cache_info().currsize == 0
    assert attempted_url is not None
    server = create_engine(postgresql_url + "/postgres")
    try:
        with server.connect() as connection:
            assert (
                connection.execute(
                    text("SELECT count(*) FROM pg_database WHERE datname = :name"),
                    {"name": make_url(attempted_url).database},
                ).scalar_one()
                == 0
            )
    finally:
        server.dispose()
