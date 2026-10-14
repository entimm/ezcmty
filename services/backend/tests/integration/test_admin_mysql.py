"""Exercise MySQL locking and real Redis without touching configured service data."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import time
from collections.abc import Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from pytest import MonkeyPatch, TempPathFactory
from redis import Redis
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.dialects.mysql import BINARY
from sqlalchemy.orm import Session, sessionmaker

from backend_app.core.admin_sessions import AdminSessionStore
from backend_app.core.config import get_settings
from backend_app.core.errors import AppError
from backend_app.db.base import Base
from backend_app.models.admin import AdminAccount, AdminAuditLog, AdminRole, AdminRolePermission
from backend_app.schemas import admin as schema
from backend_app.services.admin import AdminService

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("APP_RUN_MYSQL_TESTS") != "1",
        reason="Set APP_RUN_MYSQL_TESTS=1 for isolated MySQL/Redis tests",
    ),
]
PASSWORD = "integration-test-password"


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@pytest.fixture(scope="session")
def mysql_redis(tmp_path_factory: TempPathFactory) -> Iterator[tuple[str, Redis[str]]]:
    mysql_binary, redis_binary = shutil.which("mysqld"), shutil.which("redis-server")
    if not mysql_binary or not redis_binary:
        pytest.skip("mysqld and redis-server are required")
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
    mysql_process = subprocess.Popen(
        [
            mysql_binary,
            "--no-defaults",
            f"--datadir={data}",
            "--bind-address=127.0.0.1",
            f"--port={mysql_port}",
            f"--socket={socket_path}",
            "--mysqlx=0",
            "--skip-log-bin",
            "--innodb-buffer-pool-size=32M",
            f"--log-error={log}",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
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
    server_url = f"mysql+pymysql://root@127.0.0.1:{mysql_port}"
    engine = create_engine(
        server_url + "/mysql", hide_parameters=True, connect_args={"connect_timeout": 1}
    )
    redis_client: Redis[str] = Redis.from_url(
        f"redis://127.0.0.1:{redis_port}/0",
        decode_responses=True,
        socket_connect_timeout=1,
        socket_timeout=2,
    )
    try:
        for _ in range(200):
            if mysql_process.poll() is not None or redis_process.poll() is not None:
                pytest.fail("Isolated service exited during startup")
            try:
                with engine.connect() as connection:
                    connection.execute(text("SELECT 1"))
                redis_client.ping()
                break
            except Exception:
                time.sleep(0.1)
        else:
            pytest.fail("Isolated service startup timed out")
        yield server_url, redis_client
    finally:
        engine.dispose()
        redis_client.close()
        for process in (mysql_process, redis_process):
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        for suffix in ("", ".lock"):
            Path(socket_path + suffix).unlink(missing_ok=True)


@pytest.fixture
def real_admin(
    mysql_redis: tuple[str, Redis[str]], monkeypatch: MonkeyPatch
) -> Iterator[tuple[sessionmaker[Session], AdminSessionStore]]:
    server_url, redis_client = mysql_redis
    name = "admin_test_" + uuid4().hex
    server = create_engine(server_url + "/mysql", hide_parameters=True)
    with server.begin() as connection:
        connection.execute(text(f"CREATE DATABASE `{name}` CHARACTER SET utf8mb4"))
    url = server_url + f"/{name}?charset=utf8mb4"
    monkeypatch.setenv("APP_DATABASE_URL", url)
    get_settings.cache_clear()
    settings = get_settings()
    command.upgrade(Config(str(Path(__file__).resolve().parents[2] / "alembic.ini")), "head")
    engine = create_engine(url, hide_parameters=True)
    factory = sessionmaker(bind=engine, autoflush=False)
    store = AdminSessionStore(redis_client, settings)
    try:
        yield factory, store
    finally:
        engine.dispose()
        with server.begin() as connection:
            connection.execute(text(f"DROP DATABASE `{name}`"))
        server.dispose()


def test_competing_super_admin_disables_preserve_one_valid_admin(
    real_admin: tuple[sessionmaker[Session], AdminSessionStore],
) -> None:
    factory, store = real_admin
    with factory() as db:
        service = AdminService(db, "platform_admin")
        service.initialize_super_admin("first", "First", PASSWORD)
        first = db.scalar(select(AdminAccount).where(AdminAccount.login_name == "first"))
        system = db.scalar(select(AdminRole).where(AdminRole.code == "super_admin"))
        assert first and system
        first.must_change_password = False
        db.commit()
        first_token, _ = store.create("platform_admin", first.id, first.session_version)
        context = service.authenticate(store, first_token)
        second = service.create_account(
            context,
            schema.AccountCreate(
                login_name="second", display_name="Second", password=PASSWORD, role_ids=[system.id]
            ),
            "create-second",
        )
        account = db.get(AdminAccount, second.id)
        assert account
        account.must_change_password = False
        db.commit()
        second_token, _ = store.create("platform_admin", account.id, account.session_version)
        first_id, second_id = first.id, account.id
    barrier = Barrier(2)

    def disable(token: str, target: str) -> str:
        with factory() as db:
            service = AdminService(db, "platform_admin")
            context = service.authenticate(store, token)
            barrier.wait(timeout=10)
            try:
                service.update_account(
                    context, target, schema.AccountUpdate(enabled=False), "concurrent-disable"
                )
                return "success"
            except AppError as error:
                db.rollback()
                return error.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(disable, first_token, second_id),
            executor.submit(disable, second_token, first_id),
        ]
        results = [future.result(timeout=15) for future in futures]
    assert sorted(results) == ["auth.unauthenticated", "success"]
    with factory() as db:
        role = db.scalar(select(AdminRole).where(AdminRole.code == "super_admin"))
        assert role
        assert len(AdminService(db, "platform_admin").repo.active_super_accounts(role.id)) == 1


def test_real_redis_revocation_and_scope_separation(
    real_admin: tuple[sessionmaker[Session], AdminSessionStore],
) -> None:
    factory, store = real_admin
    with factory() as db:
        service = AdminService(db, "platform_admin")
        service.initialize_super_admin("admin", "Admin", PASSWORD)
        account = db.scalar(select(AdminAccount))
        assert account
        account.must_change_password = False
        db.commit()
        token, _ = store.create("platform_admin", account.id, account.session_version)
        assert store.read("property_admin", token) is None
        context = service.authenticate(store, token)
        service.change_password(
            context,
            schema.PasswordChange(current_password=PASSWORD, new_password="another-test-password"),
            "password-change",
        )
        assert store.read("platform_admin", token) is not None
    with factory() as db:
        with pytest.raises(AppError) as caught:
            AdminService(db, "platform_admin").authenticate(store, token)
        assert caught.value.code == "auth.unauthenticated"
    # Real Lua counters enforce both account and source limits.
    source = uuid4().hex
    for _ in range(store.settings.admin_login_limit):
        store.limit_login("platform_admin", "limit-" + source, source)
    with pytest.raises(AppError) as caught:
        store.limit_login("platform_admin", "other-" + source, source)
    assert caught.value.code == "auth.rate_limited"


def test_uuid_binary_storage_and_fresh_migration_schema(
    real_admin: tuple[sessionmaker[Session], AdminSessionStore],
) -> None:
    factory, _ = real_admin
    legacy_id = str(uuid4())
    with factory() as db:
        service = AdminService(db, "platform_admin")
        service.initialize_super_admin("admin", "Admin", PASSWORD)
        account = db.scalar(select(AdminAccount))
        assert account is not None and UUID(account.id).version == 7
        account_id = account.id
        role = AdminRole(scope="platform_admin", code="uuid_reader", name="Reader")
        db.add(role)
        db.add(
            AdminAccount(
                id=legacy_id,
                scope="platform_admin",
                login_name="legacy",
                display_name="Legacy",
                password_hash=account.password_hash,
            )
        )
        db.flush()
        db.add(
            AdminRolePermission(
                scope="platform_admin", role_id=role.id, permission="admin.account.read"
            )
        )
        db.add(
            AdminAuditLog(
                scope="platform_admin",
                actor_id=legacy_id,
                action="uuid.test",
                target_type="account",
                target_id=account_id,
                result="success",
                request_id="uuid-test",
            )
        )
        db.add(
            AdminAuditLog(
                scope="platform_admin",
                action="uuid.null-test",
                target_type="account",
                result="failure",
                request_id="uuid-null-test",
            )
        )
        db.commit()
        connection = db.connection()
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
        inspector = inspect(connection)
        uuid_columns = {"id", "account_id", "role_id", "actor_id", "target_id"}
        for table in Base.metadata.sorted_tables:
            columns = {column["name"]: column for column in inspector.get_columns(table.name)}
            assert columns["created_at"]["nullable"] is False
            for name in uuid_columns & columns.keys():
                uuid_type = columns[name]["type"]
                assert isinstance(uuid_type, BINARY)
                assert uuid_type.length == 16
            values: Sequence[datetime] = (
                connection.execute(text(f"SELECT created_at FROM `{table.name}`")).scalars().all()
            )
            assert values and all(value is not None for value in values)
        for identifier in (account_id, legacy_id):
            row = (
                connection.execute(
                    text(
                        "SELECT id, BIN_TO_UUID(id) AS text_id FROM admin_accounts "
                        "WHERE id = UUID_TO_BIN(:identifier)"
                    ),
                    {"identifier": identifier},
                )
                .mappings()
                .one()
            )
            assert row["id"] == UUID(identifier).bytes and row["text_id"] == identifier
            entity = db.get(AdminAccount, identifier)
            assert entity is not None and entity.id == identifier
        references = connection.execute(
            text("SELECT actor_id, target_id FROM admin_audit_logs WHERE action = 'uuid.test'")
        ).one()
        assert references == (UUID(legacy_id).bytes, UUID(account_id).bytes)
        nullable = connection.execute(
            text("SELECT actor_id, target_id FROM admin_audit_logs WHERE action = 'uuid.null-test'")
        ).one()
        assert nullable == (None, None)
