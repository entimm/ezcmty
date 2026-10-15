from __future__ import annotations

import os
import shutil
import subprocess
import time
from collections.abc import Iterator
from contextlib import ExitStack

import pytest
from pytest import MonkeyPatch
from redis import Redis
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from tests.support.postgresql import free_port, stop_service

from backend_app.core.admin_sessions import AdminSessionStore
from backend_app.core.config import get_settings


@pytest.fixture(scope="session")
def real_redis() -> Iterator[Redis[str]]:
    if os.environ.get("APP_RUN_POSTGRESQL_TESTS") != "1":
        pytest.skip("Set APP_RUN_POSTGRESQL_TESTS=1 for isolated PostgreSQL/Redis tests")
    binary = shutil.which("redis-server")
    if not binary:
        pytest.fail("Requested PostgreSQL/Redis tests require redis-server on PATH")
    port = free_port()
    with ExitStack() as cleanup:
        process = subprocess.Popen(
            [
                binary,
                "--bind",
                "127.0.0.1",
                "--port",
                str(port),
                "--save",
                "",
                "--appendonly",
                "no",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        cleanup.callback(stop_service, process)
        client: Redis[str] = Redis.from_url(
            f"redis://127.0.0.1:{port}/0",
            decode_responses=True,
            socket_connect_timeout=1,
            socket_timeout=2,
        )
        cleanup.callback(client.close)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if process.poll() is not None:
                pytest.fail("Isolated Redis exited during startup")
            try:
                client.ping()
                break
            except Exception:
                time.sleep(0.1)
        else:
            pytest.fail("Isolated Redis startup timed out")
        yield client


@pytest.fixture
def real_admin(
    migrated_database_url: str,
    real_redis: Redis[str],
    monkeypatch: MonkeyPatch,
) -> Iterator[tuple[sessionmaker[Session], AdminSessionStore]]:
    real_redis.flushdb()
    engine = create_engine(
        migrated_database_url,
        hide_parameters=True,
        connect_args={"options": "-c timezone=UTC"},
    )
    try:
        yield (
            sessionmaker(bind=engine, autoflush=False),
            AdminSessionStore(real_redis, get_settings()),
        )
    finally:
        engine.dispose()
        real_redis.flushdb()
