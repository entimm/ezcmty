from __future__ import annotations

from collections.abc import Generator, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from redis import Redis
from sqlalchemy import create_engine, event, func, inspect, select
from sqlalchemy.orm import Session, sessionmaker

from backend_app.api.admin import get_admin_session_store
from backend_app.app_factory import create_app
from backend_app.core.admin_security import hash_password, verify_password
from backend_app.core.admin_sessions import AdminSessionStore
from backend_app.core.config import get_settings
from backend_app.core.errors import AppError
from backend_app.db.session import get_database_session
from backend_app.models.admin import AdminAccount, AdminAccountRole, AdminAuditLog, AdminRole
from backend_app.schemas import admin as schema
from backend_app.services.admin import AdminService

TEST_PASSWORD = "test-initial-password"
NEW_PASSWORD = "test-changed-password"
ORIGIN = "http://127.0.0.1:5173"


class MemoryRedis:
    def __init__(self) -> None:
        self.now = 1000.0
        self.values: dict[str, tuple[str, float]] = {}

    def get(self, key: str) -> str | None:
        item = self.values.get(key)
        return item[0] if item and item[1] > self.now else None

    def setex(self, key: str, ttl: int, value: str) -> None:
        self.values[key] = (value, self.now + ttl)

    def delete(self, key: str) -> None:
        self.values.pop(key, None)

    def expire(self, key: str, ttl: int) -> bool:
        value = self.get(key)
        if value is None:
            return False
        self.setex(key, ttl, value)
        return True

    def eval(self, script: str, key_count: int, *args: Any) -> int:
        exceeded = False
        window, limit = args[-2:]
        for key in args[:key_count]:
            item = self.values.get(key)
            count = int(self.get(key) or 0) + 1
            self.values[key] = (
                str(count),
                item[1] if item and item[1] > self.now else self.now + window,
            )
            exceeded |= count > limit
        return int(exceeded)


@dataclass
class Harness:
    client: TestClient
    factory: sessionmaker[Session]
    redis: MemoryRedis
    store: AdminSessionStore

    def login(self, name: str = "root", password: str = NEW_PASSWORD) -> dict[str, Any]:
        response = self.client.post(
            "/v1/admin-sessions",
            json={"login_name": name, "password": password},
            headers={"Origin": ORIGIN},
        )
        assert response.status_code == 201, response.text
        return cast(dict[str, Any], response.json())

    def headers(self) -> dict[str, str]:
        response = self.client.get("/v1/admin-sessions/current")
        assert response.status_code == 200
        return {"Origin": ORIGIN, "X-CSRF-Token": response.json()["csrf_token"]}


@pytest.fixture
def harness(tmp_path: Path, monkeypatch: MonkeyPatch) -> Iterator[Harness]:
    url = f"sqlite:///{tmp_path / 'admin.sqlite'}"
    monkeypatch.setenv("APP_DATABASE_URL", url)
    monkeypatch.setenv("APP_ADMIN_LOGIN_LIMIT", "10000")
    get_settings.cache_clear()
    settings = get_settings()
    backend = Path(__file__).resolve().parents[2]
    command.upgrade(Config(str(backend / "alembic.ini")), "head")
    engine = create_engine(url, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def enforce_foreign_keys(connection: Any, record: Any) -> None:
        connection.execute("PRAGMA foreign_keys=ON")

    assert set(inspect(engine).get_table_names()) == {
        "alembic_version",
        "admin_accounts",
        "admin_roles",
        "admin_account_roles",
        "admin_role_permissions",
        "admin_audit_logs",
    }
    factory = sessionmaker(bind=engine, autoflush=False)
    with factory() as db:
        AdminService(db, "platform_admin").initialize_super_admin(
            "root", "平台管理员", TEST_PASSWORD
        )
    redis = MemoryRedis()
    monkeypatch.setattr("backend_app.core.admin_sessions.time", lambda: redis.now)
    store = AdminSessionStore(cast("Redis[str]", redis), settings)
    app = create_app("platform-admin-api")

    def database() -> Generator[Session]:
        with factory() as db:
            try:
                yield db
            except BaseException:
                db.rollback()
                raise

    app.dependency_overrides[get_database_session] = database
    app.dependency_overrides[get_admin_session_store] = lambda: store
    # Use the deployed API prefix, so Cookie Path isolation is exercised.
    from fastapi import FastAPI

    outer = FastAPI()
    outer.mount("/api/platform", app)
    with TestClient(outer, base_url="http://testserver/api/platform") as client:
        value = Harness(client, factory, redis, store)
        value.login(password=TEST_PASSWORD)
        headers = value.headers()
        result = client.post(
            "/v1/admin-accounts/me/password-changes",
            json={"current_password": TEST_PASSWORD, "new_password": NEW_PASSWORD},
            headers=headers,
        )
        assert result.status_code == 204, result.text
        yield value
    engine.dispose()


def test_login_cookie_and_restricted_session(harness: Harness) -> None:
    with harness.factory() as db:
        account = db.scalar(select(AdminAccount).where(AdminAccount.login_name == "root"))
        assert account
        account.must_change_password = True
        db.commit()
    login = harness.client.post(
        "/v1/admin-sessions",
        json={"login_name": "root", "password": NEW_PASSWORD},
        headers={"Origin": ORIGIN},
    )
    assert login.status_code == 201
    assert login.json()["permissions"] == []
    cookie = login.headers["set-cookie"]
    assert "HttpOnly" in cookie and "Path=/api/platform" in cookie and "SameSite=lax" in cookie
    assert login.headers["cache-control"] == "no-store"
    for path in (
        "/v1/admin-accounts/me",
        "/v1/admin-accounts",
        "/v1/admin-roles",
        "/v1/admin-audit-logs",
    ):
        response = harness.client.get(path)
        assert (
            response.status_code == 403
            and response.json()["code"] == "auth.password_change_required"
        )
    changed = harness.client.post(
        "/v1/admin-accounts/me/password-changes",
        json={"current_password": NEW_PASSWORD, "new_password": TEST_PASSWORD},
        headers=harness.headers(),
    )
    assert changed.status_code == 204 and "Path=/api/platform" in changed.headers["set-cookie"]


def test_credentials_fail_uniformly_and_old_password_is_not_401(harness: Harness) -> None:
    responses = []
    for name, password in (("missing", NEW_PASSWORD), ("root", "wrong-password")):
        responses.append(
            harness.client.post(
                "/v1/admin-sessions",
                json={"login_name": name, "password": password},
                headers={"Origin": ORIGIN},
            )
        )
    assert all(
        response.status_code == 401 and response.json()["code"] == "auth.invalid_credentials"
        for response in responses
    )
    harness.login()
    response = harness.client.post(
        "/v1/admin-accounts/me/password-changes",
        json={"current_password": "wrong-password", "new_password": TEST_PASSWORD},
        headers=harness.headers(),
    )
    assert response.status_code == 409 and response.json()["code"] == "auth.invalid_old_password"
    assert harness.client.get("/v1/admin-sessions/current").status_code == 200


def test_origin_and_csrf_are_required(harness: Harness) -> None:
    harness.login()
    for headers in (
        {},
        {"Origin": ORIGIN},
        {"Origin": "https://evil.test", "X-CSRF-Token": harness.headers()["X-CSRF-Token"]},
    ):
        response = harness.client.patch(
            "/v1/admin-accounts/me", json={"display_name": "新名称"}, headers=headers
        )
        assert response.status_code == 403 and response.json()["code"] == "auth.csrf_failed"
    assert (
        harness.client.patch(
            "/v1/admin-accounts/me", json={"display_name": "新名称"}, headers=harness.headers()
        ).status_code
        == 200
    )


def test_multi_sessions_logout_and_cross_scope_isolation(harness: Harness) -> None:
    harness.login()
    first = harness.client.cookies.get("admin_session")
    harness.login()
    second = harness.client.cookies.get("admin_session")
    assert first and second and first != second
    assert harness.store.read("property_admin", first) is None
    assert (
        harness.client.delete("/v1/admin-sessions/current", headers=harness.headers()).status_code
        == 204
    )
    assert harness.store.read("platform_admin", second) is None
    assert harness.store.read("platform_admin", first) is not None
    assert "/v1/admin-sessions" not in create_app("property-admin-api").openapi()["paths"]


def test_role_write_rules_revocation_and_account_creation(harness: Harness) -> None:
    harness.login()
    headers = harness.headers()
    role = harness.client.post(
        "/v1/admin-roles", json={"code": "reader", "name": "只读管理员"}, headers=headers
    ).json()
    result = harness.client.put(
        f"/v1/admin-roles/{role['id']}/permissions",
        json={"permissions": ["admin.account.create"]},
        headers=headers,
    )
    assert result.status_code == 409 and result.json()["code"] == "admin.invalid_permission"
    assert (
        harness.client.put(
            f"/v1/admin-roles/{role['id']}/permissions",
            json={"permissions": ["admin.account.read", "admin.role.read"]},
            headers=headers,
        ).status_code
        == 200
    )
    result = harness.client.post(
        "/v1/admin-accounts",
        json={
            "login_name": "reader",
            "display_name": "查询账号",
            "password": TEST_PASSWORD,
            "role_ids": [role["id"]],
        },
        headers=headers,
    )
    assert result.status_code == 201
    account = result.json()
    with harness.factory() as db:
        saved = db.get(AdminAccount, account["id"])
        assert (
            saved
            and saved.password_hash != TEST_PASSWORD
            and verify_password(saved.password_hash, TEST_PASSWORD)
        )
        saved.must_change_password = False
        db.commit()
        token, stored = harness.store.create("platform_admin", saved.id, saved.session_version)
    with harness.factory() as db:
        service = AdminService(db, "platform_admin")
        context = service.authenticate(harness.store, token)
        assert context.permissions == ["admin.account.read", "admin.role.read"]
        with pytest.raises(AppError, match="没有操作权限"):
            service.create_role(context, schema.RoleCreate(code="illegal", name="不允许"), "test")
        db.rollback()
    assert (
        harness.client.put(
            f"/v1/admin-roles/{role['id']}/permissions", json={"permissions": []}, headers=headers
        ).status_code
        == 200
    )
    assert harness.store.read("platform_admin", token) is not None
    with harness.factory() as db:
        with pytest.raises(AppError) as caught:
            AdminService(db, "platform_admin").authenticate(harness.store, token)
        assert caught.value.code == "auth.unauthenticated"
    audit = harness.client.get("/v1/admin-audit-logs").json()["items"]
    assert any(
        entry["target_id"] == account["id"] and entry["action"] == "account.create"
        for entry in audit
    )
    assert TEST_PASSWORD not in str(audit) and stored.csrf_token not in str(audit)


def test_super_admin_protection_and_fixed_role(harness: Harness) -> None:
    session = harness.login()
    headers = harness.headers()
    root = session["subject_id"]
    role = harness.client.get("/v1/admin-roles").json()["items"][0]
    disabled = harness.client.patch(
        f"/v1/admin-accounts/{root}", json={"enabled": False}, headers=headers
    )
    assert disabled.status_code == 409 and disabled.json()["code"] == "admin.protected_account"
    removed = harness.client.put(
        f"/v1/admin-accounts/{root}/roles", json={"role_ids": []}, headers=headers
    )
    assert removed.status_code == 409 and removed.json()["code"] == "admin.protected_account"
    fixed = harness.client.patch(
        f"/v1/admin-roles/{role['id']}", json={"enabled": False}, headers=headers
    )
    assert fixed.status_code == 409 and fixed.json()["code"] == "admin.system_role_readonly"
    with harness.factory() as db:
        with pytest.raises(AppError):
            AdminService(db, "platform_admin").initialize_super_admin(
                "another", "管理员", TEST_PASSWORD
            )
        db.rollback()
        assert db.scalar(select(func.count()).select_from(AdminAccount)) == 1


def test_disabled_roles_retained_but_cannot_be_added(harness: Harness) -> None:
    harness.login()
    headers = harness.headers()
    role = harness.client.post(
        "/v1/admin-roles", json={"code": "disabled", "name": "停用角色"}, headers=headers
    ).json()
    account = harness.client.post(
        "/v1/admin-accounts",
        json={
            "login_name": "member",
            "display_name": "成员",
            "password": TEST_PASSWORD,
            "role_ids": [role["id"]],
        },
        headers=headers,
    ).json()
    assert (
        harness.client.patch(
            f"/v1/admin-roles/{role['id']}", json={"enabled": False}, headers=headers
        ).status_code
        == 200
    )
    assert (
        harness.client.put(
            f"/v1/admin-accounts/{account['id']}/roles",
            json={"role_ids": [role["id"]]},
            headers=headers,
        ).status_code
        == 200
    )
    assert (
        harness.client.put(
            f"/v1/admin-accounts/{account['id']}/roles", json={"role_ids": []}, headers=headers
        ).status_code
        == 200
    )
    assert (
        harness.client.put(
            f"/v1/admin-accounts/{account['id']}/roles",
            json={"role_ids": [role["id"]]},
            headers=headers,
        ).status_code
        == 409
    )


def test_account_and_audit_roll_back_together(harness: Harness, monkeypatch: MonkeyPatch) -> None:
    harness.login()
    headers = harness.headers()
    monkeypatch.setattr(
        "backend_app.repositories.admin.AdminRepository.audit",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("audit failed")),
    )
    response = harness.client.post(
        "/v1/admin-accounts",
        json={
            "login_name": "rolledback",
            "display_name": "回滚",
            "password": TEST_PASSWORD,
            "role_ids": [],
        },
        headers=headers,
    )
    assert response.status_code == 500
    with harness.factory() as db:
        assert (
            db.scalar(select(AdminAccount).where(AdminAccount.login_name == "rolledback")) is None
        )


def test_session_lifetimes_and_rate_limit(harness: Harness) -> None:
    settings = harness.store.settings.model_copy(
        update={
            "admin_session_idle_seconds": 60,
            "admin_session_absolute_seconds": 120,
            "admin_login_limit": 2,
        }
    )
    store = AdminSessionStore(cast("Redis[str]", harness.redis), settings)
    token, stored = store.create("platform_admin", "account", 1)
    harness.redis.now += 50
    store.touch("platform_admin", token, stored)
    harness.redis.now += 50
    store.touch("platform_admin", token, stored)
    harness.redis.now += 21
    assert store.read("platform_admin", token) is None
    token, _ = store.create("platform_admin", "idle", 1)
    harness.redis.now += 61
    assert store.read("platform_admin", token) is None
    store.limit_login("platform_admin", "account", "source")
    store.limit_login("platform_admin", "account", "source")
    with pytest.raises(AppError) as caught:
        store.limit_login("platform_admin", "account", "source")
    assert caught.value.code == "auth.rate_limited"


def test_scope_foreign_keys_and_hidden_resources(harness: Harness) -> None:
    from sqlalchemy.exc import IntegrityError

    harness.login()
    with harness.factory() as db:
        property_account = AdminAccount(
            scope="property_admin",
            login_name="root",
            display_name="物业",
            password_hash=hash_password(TEST_PASSWORD),
        )
        db.add(property_account)
        db.commit()
        property_id = property_account.id
        platform_role = db.scalar(select(AdminRole).where(AdminRole.scope == "platform_admin"))
        assert platform_role
        db.add(
            AdminAccountRole(
                scope="property_admin", account_id=property_id, role_id=platform_role.id
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
    assert harness.client.get(f"/v1/admin-accounts/{property_id}").status_code == 404
    assert all(
        entry["scope"] == "platform_admin"
        for entry in harness.client.get("/v1/admin-accounts").json()["items"]
    )
    with harness.factory() as db:
        assert db.scalar(select(func.count()).select_from(AdminAuditLog))


@pytest.mark.parametrize(
    ("platform_path", "property_path"),
    [
        ("/api/admin", "/api/admin"),
        ("/api/admin", "/api/admin/"),
        ("/api/admin/", "/api/admin"),
        ("/api", "/api/admin"),
        ("/api/admin", "/api"),
        ("/", "/api/property"),
    ],
)
def test_overlapping_cookie_paths_are_rejected(
    monkeypatch: MonkeyPatch, platform_path: str, property_path: str
) -> None:
    monkeypatch.setenv("APP_PLATFORM_ADMIN_COOKIE_PATH", platform_path)
    monkeypatch.setenv("APP_PROPERTY_ADMIN_COOKIE_PATH", property_path)
    with pytest.raises(ValueError, match="cookie paths"):
        get_settings()


def test_sibling_cookie_paths_remain_isolated(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("APP_PLATFORM_ADMIN_COOKIE_PATH", "/api/admin")
    monkeypatch.setenv("APP_PROPERTY_ADMIN_COOKIE_PATH", "/api/admin-property")
    settings = get_settings()
    assert settings.platform_admin_cookie_path == "/api/admin"
    assert settings.property_admin_cookie_path == "/api/admin-property"
