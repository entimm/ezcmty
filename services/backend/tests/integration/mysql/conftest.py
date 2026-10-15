from __future__ import annotations

import os
import shutil
import socket
import subprocess
import time
from collections.abc import Iterator
from contextlib import ExitStack
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from pytest import MonkeyPatch, TempPathFactory
from redis import Redis
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from tests.support.paths import BACKEND_ROOT

from backend_app.core.admin_sessions import AdminSessionStore
from backend_app.core.config import get_settings


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


@pytest.fixture(scope="session")
def mysql_redis(tmp_path_factory: TempPathFactory) -> Iterator[tuple[str, Redis[str]]]:
    if os.environ.get("APP_RUN_MYSQL_TESTS") != "1":
        pytest.skip("Set APP_RUN_MYSQL_TESTS=1 for isolated MySQL/Redis tests")
    mysql_binary, redis_binary = shutil.which("mysqld"), shutil.which("redis-server")
    if not mysql_binary or not redis_binary:
        pytest.fail("Requested MySQL/Redis tests require mysqld and redis-server on PATH")
    base = tmp_path_factory.mktemp("admin-services")
    data = base / "mysql"
    data.mkdir()
    log = base / "mysql.log"
    subprocess.run(
        [
            mysql_binary,
            "--no-defaults",
            "--initialize-insecure",
            f"--datadir={data}",
            f"--log-error={log}",
        ],
        check=True,
        capture_output=True,
    )
    mysql_port, redis_port = free_port(), free_port()
    socket_path = f"/tmp/admin-test-{uuid4().hex}.sock"
    with ExitStack() as cleanup:
        for suffix in ("", ".lock"):
            cleanup.callback(Path(socket_path + suffix).unlink, missing_ok=True)
        mysql_process = subprocess.Popen(
            [
                mysql_binary,
                "--no-defaults",
                f"--datadir={data}",
                f"--port={mysql_port}",
                "--bind-address=127.0.0.1",
                f"--socket={socket_path}",
                "--mysqlx=0",
                "--skip-log-bin",
                "--innodb-buffer-pool-size=32M",
                f"--log-error={log}",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        cleanup.callback(stop_service, mysql_process)
        redis_process = subprocess.Popen(
            [
                redis_binary,
                "--bind",
                "127.0.0.1",
                "--port",
                str(redis_port),
                "--save",
                "",
                "--appendonly",
                "no",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        cleanup.callback(stop_service, redis_process)
        server_url = f"mysql+pymysql://root@127.0.0.1:{mysql_port}"
        engine = create_engine(
            server_url + "/mysql", hide_parameters=True, connect_args={"connect_timeout": 1}
        )
        cleanup.callback(engine.dispose)
        redis_client: Redis[str] = Redis.from_url(
            f"redis://127.0.0.1:{redis_port}/0",
            decode_responses=True,
            socket_connect_timeout=1,
            socket_timeout=2,
        )
        cleanup.callback(redis_client.close)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if mysql_process.poll() is not None or redis_process.poll() is not None:
                pytest.fail("Isolated service exited during startup")
            try:
                with engine.connect() as connection:
                    connection.exec_driver_sql("SELECT 1")
                redis_client.ping()
                break
            except Exception:
                time.sleep(0.1)
        else:
            pytest.fail("Isolated service startup timed out")
        yield server_url, redis_client


@pytest.fixture
def real_admin(
    mysql_redis: tuple[str, Redis[str]], monkeypatch: MonkeyPatch
) -> Iterator[tuple[sessionmaker[Session], AdminSessionStore]]:
    server_url, redis_client = mysql_redis
    name = "admin_test_" + uuid4().hex
    with ExitStack() as cleanup:
        server = create_engine(server_url + "/mysql", hide_parameters=True)
        cleanup.callback(server.dispose)
        with server.begin() as connection:
            connection.exec_driver_sql(f"CREATE DATABASE `{name}` CHARACTER SET utf8mb4")

        def drop_database() -> None:
            with server.begin() as connection:
                connection.exec_driver_sql(f"DROP DATABASE `{name}`")

        cleanup.callback(drop_database)
        redis_client.flushdb()
        cleanup.callback(redis_client.flushdb)
        url = server_url + f"/{name}?charset=utf8mb4"
        monkeypatch.setenv("APP_DATABASE_URL", url)
        get_settings.cache_clear()
        settings = get_settings()
        command.upgrade(Config(str(BACKEND_ROOT / "alembic.ini")), "head")
        engine = create_engine(url, hide_parameters=True)
        cleanup.callback(engine.dispose)
        yield sessionmaker(bind=engine, autoflush=False), AdminSessionStore(redis_client, settings)
