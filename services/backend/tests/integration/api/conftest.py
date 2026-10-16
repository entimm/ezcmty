from __future__ import annotations

from collections.abc import Generator, Iterator
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from redis import Redis
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session, sessionmaker
from tests.support.admin import NEW_PASSWORD, TEST_PASSWORD, Harness, admin, company
from tests.support.redis import MemoryRedis
from tests.support.resident import FakeWechat, ResidentHarness
from tests.support.workspace import WorkspaceHarness, create_community

from backend_app.api.admin import get_admin_session_store
from backend_app.api.resident.identity import get_resident_session_store, get_wechat_miniapp
from backend_app.app_factory import create_app
from backend_app.core.admin_sessions import AdminSessionStore
from backend_app.core.config import get_settings
from backend_app.core.resident_sessions import ResidentSessionStore
from backend_app.db.session import get_database_session
from backend_app.services.platform_admin.admin import PlatformAdminService


@pytest.fixture
def harness(migrated_database_url: str, monkeypatch: MonkeyPatch) -> Iterator[Harness]:
    url = migrated_database_url
    monkeypatch.setenv("APP_DATABASE_URL", url)
    monkeypatch.setenv("APP_ADMIN_LOGIN_LIMIT", "10000")
    get_settings.cache_clear()
    settings = get_settings()
    engine = create_engine(url, connect_args={"options": "-c timezone=UTC"})

    try:
        assert set(inspect(engine).get_table_names()) == {
            "alembic_version",
            "house_claim_applications",
            "resident_house_bindings",
            "miniapp_users",
            "miniapp_phone_bindings",
            "miniapp_phone_verifications",
            "admin_accounts",
            "admin_roles",
            "admin_account_roles",
            "admin_role_permissions",
            "admin_audit_logs",
            "property_companies",
            "communities",
            "community_space_nodes",
            "houses",
            "house_owners",
            "property_fee_basis_versions",
            "bills",
            "bill_settlement_entries",
            "bill_operations",
        }
        factory = sessionmaker(bind=engine, autoflush=False)
        with factory() as db:
            PlatformAdminService(db).initialize_super_admin("root", "平台管理员", TEST_PASSWORD)
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
    finally:
        engine.dispose()


@pytest.fixture
def workspace(harness: Harness) -> Iterator[WorkspaceHarness]:
    harness.login()
    company_data = company(harness)
    community_data = create_community(harness, company_data["id"], "first-community")
    account_data = admin(harness, company_data["id"])
    enabled = harness.client.patch(
        f"/v1/property-companies/{company_data['id']}",
        json={"enabled": True},
        headers=harness.headers(),
    )
    assert enabled.status_code == 200, enabled.text
    property_app = create_app("property-admin-api")

    def database() -> Generator[Session]:
        with harness.factory() as db:
            try:
                yield db
            except BaseException:
                db.rollback()
                raise

    property_app.dependency_overrides[get_database_session] = database
    property_app.dependency_overrides[get_admin_session_store] = lambda: harness.store
    outer = FastAPI()
    outer.mount("/api/property", property_app)
    with TestClient(outer, raise_server_exceptions=False) as client:
        yield WorkspaceHarness(
            client=client,
            platform=harness,
            company_id=company_data["id"],
            account_id=account_data["id"],
            community_id=community_data["id"],
        )


@pytest.fixture
def resident(harness: Harness, monkeypatch: MonkeyPatch) -> Iterator[ResidentHarness]:
    store = ResidentSessionStore(cast("Redis[str]", harness.redis), harness.store.settings)
    monkeypatch.setattr("backend_app.core.resident_sessions.time", lambda: harness.redis.now)
    wechat = FakeWechat()
    app = create_app("resident-api")

    def database() -> Generator[Session]:
        with harness.factory() as db:
            yield db

    app.dependency_overrides[get_database_session] = database
    app.dependency_overrides[get_resident_session_store] = lambda: store
    app.dependency_overrides[get_wechat_miniapp] = lambda: wechat
    with TestClient(app) as client:
        value = ResidentHarness(client, store, wechat)
        value.login()
        yield value
