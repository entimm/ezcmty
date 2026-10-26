from __future__ import annotations

import shutil
import socket
import subprocess
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from pytest import MonkeyPatch
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from backend_app.core.config import get_settings
from backend_app.core.error_catalog import CONTRACT_VERSION
from tests.support.paths import BACKEND_ROOT


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def stop_service(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is None:
        process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


@contextmanager
def postgresql_server(directory: Path) -> Iterator[str]:
    binaries = {name: shutil.which(name) for name in ("initdb", "postgres", "pg_ctl")}
    if not all(binaries.values()):
        pytest.fail("PostgreSQL integration tests require initdb, postgres and pg_ctl on PATH")
    data = directory / "data"
    subprocess.run(
        [
            str(binaries["initdb"]),
            "-D",
            str(data),
            "-U",
            "postgres",
            "-A",
            "trust",
            "--encoding=UTF8",
            "--locale-provider=builtin",
            "--builtin-locale=C.UTF-8",
            "--no-sync",
        ],
        check=True,
        capture_output=True,
    )
    port = free_port()
    with (directory / "postgresql.log").open("wb") as log:
        process = subprocess.Popen(
            [
                str(binaries["postgres"]),
                "-D",
                str(data),
                "-h",
                "127.0.0.1",
                "-p",
                str(port),
                "-k",
                "",
                "-c",
                "timezone=UTC",
                "-c",
                "fsync=off",
                "-c",
                "synchronous_commit=off",
                "-c",
                "full_page_writes=off",
            ],
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        url = f"postgresql+psycopg://postgres@127.0.0.1:{port}"
        engine = create_engine(url + "/postgres", connect_args={"connect_timeout": 1})
        try:
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    pytest.fail("Isolated PostgreSQL exited during startup")
                try:
                    with engine.connect() as connection:
                        connection.exec_driver_sql("SELECT 1")
                    break
                except Exception:
                    time.sleep(0.1)
            else:
                pytest.fail("Isolated PostgreSQL startup timed out")
            yield url
        finally:
            engine.dispose()
            if process.poll() is None:
                subprocess.run(
                    [str(binaries["pg_ctl"]), "-D", str(data), "stop", "-m", "fast", "-t", "5"],
                    check=True,
                    capture_output=True,
                    timeout=10,
                )
            process.wait(timeout=5)


@contextmanager
def temporary_database(server_url: str, *, template: str = "template0") -> Iterator[str]:
    name = "test_" + uuid4().hex
    server = create_engine(server_url + "/postgres", isolation_level="AUTOCOMMIT")
    try:
        with server.connect() as connection:
            quoted_template = server.dialect.identifier_preparer.quote_identifier(template)
            connection.exec_driver_sql(f'CREATE DATABASE "{name}" TEMPLATE {quoted_template}')
        try:
            yield server_url + "/" + name
        finally:
            with server.connect() as connection:
                connection.exec_driver_sql(f'DROP DATABASE "{name}" WITH (FORCE)')
    finally:
        server.dispose()


@contextmanager
def migrated_database_template(server_url: str) -> Iterator[str]:
    with temporary_database(server_url) as url:
        with MonkeyPatch.context() as environment:
            environment.setenv("APP_ENV", "test")
            environment.setenv("APP_DATABASE_URL", url)
            environment.setenv("APP_REDIS_URL", "redis://127.0.0.1:6379/0")
            environment.setenv("APP_VERSION", CONTRACT_VERSION)
            get_settings.cache_clear()
            try:
                command.upgrade(Config(str(BACKEND_ROOT / "alembic.ini")), "head")
            finally:
                get_settings.cache_clear()
        name = make_url(url).database
        assert name is not None
        server = create_engine(server_url + "/postgres", isolation_level="AUTOCOMMIT")
        try:
            with server.connect() as connection:
                connection.exec_driver_sql(f'ALTER DATABASE "{name}" ALLOW_CONNECTIONS false')
            yield name
        finally:
            server.dispose()
