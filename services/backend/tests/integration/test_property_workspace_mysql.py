"""Verify property HTTP flows and status races on isolated MySQL/Redis instances."""

from __future__ import annotations

import os
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from typing import Literal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from sqlalchemy.orm import Session, sessionmaker
from tests.integration.test_admin_mysql import PASSWORD
from tests.integration.test_admin_mysql import mysql_redis as mysql_redis
from tests.integration.test_admin_mysql import real_admin as real_admin
from tests.integration.test_property_mysql import platform_token

from backend_app.api.admin import get_admin_session_store
from backend_app.app_factory import create_app
from backend_app.core.admin_security import verify_password
from backend_app.core.admin_sessions import AdminSessionStore
from backend_app.core.errors import AppError
from backend_app.core.identifiers import new_id
from backend_app.db.session import get_database_session
from backend_app.models.admin import AdminAccount
from backend_app.repositories.admin import AdminRepository
from backend_app.schemas import admin as admin_schema
from backend_app.schemas import property as schema
from backend_app.services.admin import AdminService
from backend_app.services.property import PropertyOnboardingService

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("APP_RUN_MYSQL_TESTS") != "1", reason="Requires isolated MySQL/Redis"
    ),
]
NEW_PASSWORD = "mysql-property-new-password"
RESET_PASSWORD = "mysql-property-reset-password"
ORIGIN = "http://127.0.0.1:5173"
Mutation = Literal["company", "account", "password"]


def provision(
    factory: sessionmaker[Session], store: AdminSessionStore
) -> tuple[str, schema.PropertyAdminAccount]:
    token = platform_token(factory, store)
    with factory() as db:
        actor = AdminService(db, "platform_admin").authenticate(store, token)
        service = PropertyOnboardingService(db)
        company = service.create_company(
            actor, schema.CompanyCreate(code=new_id(), name="物业公司"), "company"
        )
        account = service.create_admin(
            actor,
            company.id,
            schema.PropertyAdminCreate(
                login_name=new_id(), display_name="物业管理员", password=PASSWORD
            ),
            "account",
        )
        service.create_admin(
            actor,
            company.id,
            schema.PropertyAdminCreate(
                login_name=new_id(), display_name="另一管理员", password=PASSWORD
            ),
            "second-account",
        )
        service.update_company(actor, company.id, schema.CompanyUpdate(enabled=True), "enable")
        return token, account


def mutate(
    factory: sessionmaker[Session],
    store: AdminSessionStore,
    token: str,
    account: schema.PropertyAdminAccount,
    mutation: Mutation,
) -> None:
    with factory() as db:
        actor = AdminService(db, "platform_admin").authenticate(store, token)
        service = PropertyOnboardingService(db)
        if mutation == "company":
            service.update_company(
                actor, account.property_company_id, schema.CompanyUpdate(enabled=False), "disable"
            )
        elif mutation == "account":
            service.update_admin(
                actor,
                account.property_company_id,
                account.id,
                admin_schema.AccountUpdate(enabled=False),
                "disable-account",
            )
        else:
            service.reset_admin_password(
                actor,
                account.property_company_id,
                account.id,
                admin_schema.PasswordReset(password=RESET_PASSWORD),
                "reset",
            )


@pytest.mark.parametrize("mutation", ["company", "account", "password"])
def test_mysql_login_rechecks_state_and_password_after_concurrent_platform_change(
    real_admin: tuple[sessionmaker[Session], AdminSessionStore],
    monkeypatch: MonkeyPatch,
    mutation: Mutation,
) -> None:
    factory, store = real_admin
    platform, account = provision(factory, store)
    observed, release = Event(), Event()
    original = AdminRepository.identity_by_login

    def identity(repo: AdminRepository, login_name: str) -> AdminAccount | None:
        result = original(repo, login_name)
        if repo.scope == "property_admin" and login_name == account.login_name:
            observed.set()
            assert release.wait(10), "Platform mutation did not finish"
        return result

    monkeypatch.setattr(AdminRepository, "identity_by_login", identity)

    def login() -> str:
        with factory() as db:
            try:
                AdminService(db, "property_admin").login(
                    admin_schema.AdminLogin(login_name=account.login_name, password=PASSWORD),
                    store,
                    account.id,
                    "racing-login",
                )
            except AppError as exc:
                return exc.code
            return "unexpected_success"

    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(login)
        try:
            assert observed.wait(10), "Property login did not read its identity"
            mutate(factory, store, platform, account, mutation)
        finally:
            release.set()
        assert pending.result(timeout=10) == "auth.invalid_credentials"


@pytest.mark.parametrize("mutation", ["company", "account", "password"])
def test_mysql_password_write_rejects_stale_context_after_platform_change(
    real_admin: tuple[sessionmaker[Session], AdminSessionStore],
    mutation: Mutation,
) -> None:
    factory, store = real_admin
    platform, account = provision(factory, store)
    token, _ = store.create("property_admin", account.id, 1)
    observed, release = Event(), Event()

    def change() -> str:
        with factory() as db:
            service = AdminService(db, "property_admin")
            context = service.authenticate(store, token)
            observed.set()
            assert release.wait(10), "Platform mutation did not finish"
            try:
                service.change_password(
                    context,
                    admin_schema.PasswordChange(
                        current_password=PASSWORD, new_password=NEW_PASSWORD
                    ),
                    "racing-password",
                )
            except AppError as exc:
                return exc.code
            return "unexpected_success"

    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(change)
        try:
            assert observed.wait(10), "Property request did not authenticate"
            mutate(factory, store, platform, account, mutation)
        finally:
            release.set()
        assert pending.result(timeout=10) == "auth.unauthenticated"
    with factory() as db:
        stored = db.get(AdminAccount, account.id)
        assert stored and stored.must_change_password and stored.session_version == 2
        assert verify_password(
            stored.password_hash, RESET_PASSWORD if mutation == "password" else PASSWORD
        )


def test_mysql_http_platform_onboarding_property_password_company_scope_and_revocation(
    real_admin: tuple[sessionmaker[Session], AdminSessionStore],
) -> None:
    factory, store = real_admin
    platform_token(factory, store)
    outer = FastAPI()

    def database() -> Generator[Session]:
        with factory() as db:
            try:
                yield db
            except BaseException:
                db.rollback()
                raise

    for prefix, runtime in (("platform", "platform-admin-api"), ("property", "property-admin-api")):
        app = create_app(runtime)
        app.dependency_overrides[get_database_session] = database
        app.dependency_overrides[get_admin_session_store] = lambda: store
        outer.mount(f"/api/{prefix}", app)

    with TestClient(outer) as client:
        login = client.post(
            "/api/platform/v1/admin-sessions",
            json={"login_name": "root", "password": PASSWORD},
            headers={"Origin": ORIGIN},
        )
        assert login.status_code == 201, login.text
        platform_headers = {"Origin": ORIGIN, "X-CSRF-Token": login.json()["csrf_token"]}
        company = client.post(
            "/api/platform/v1/property-companies",
            json={"code": "own", "name": "本公司"},
            headers=platform_headers,
        ).json()
        own = client.post(
            "/api/platform/v1/communities",
            json={
                "property_company_id": company["id"],
                "code": "own",
                "name": "本小区",
                "address": "地址",
            },
            headers=platform_headers,
        ).json()
        account = client.post(
            f"/api/platform/v1/property-companies/{company['id']}/admin-accounts",
            json={"login_name": new_id(), "display_name": "物业管理员", "password": PASSWORD},
            headers=platform_headers,
        ).json()
        assert (
            client.patch(
                f"/api/platform/v1/property-companies/{company['id']}",
                json={"enabled": True},
                headers=platform_headers,
            ).status_code
            == 200
        )
        other = client.post(
            "/api/platform/v1/property-companies",
            json={"code": "other", "name": "另一公司"},
            headers=platform_headers,
        ).json()
        outside = client.post(
            "/api/platform/v1/communities",
            json={
                "property_company_id": other["id"],
                "code": "outside",
                "name": "另一小区",
                "address": "地址",
            },
            headers=platform_headers,
        ).json()
        first = client.post(
            "/api/property/v1/admin-sessions",
            json={"login_name": account["login_name"], "password": PASSWORD},
            headers={"Origin": ORIGIN},
        )
        assert first.status_code == 201 and first.json()["must_change_password"]
        assert "Path=/api/property" in first.headers["set-cookie"]
        assert client.get("/api/property/v1/property-companies/current").status_code == 403
        assert (
            client.post(
                "/api/property/v1/admin-accounts/me/password-changes",
                json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
                headers={"Origin": ORIGIN, "X-CSRF-Token": first.json()["csrf_token"]},
            ).status_code
            == 204
        )
        assert client.get("/api/platform/v1/admin-sessions/current").status_code == 200
        assert client.get("/api/property/v1/admin-sessions/current").status_code == 401
        full = client.post(
            "/api/property/v1/admin-sessions",
            json={"login_name": account["login_name"], "password": NEW_PASSWORD},
            headers={"Origin": ORIGIN},
        )
        assert full.status_code == 201 and not full.json()["must_change_password"]
        assert (
            client.get("/api/property/v1/property-companies/current").json()["id"] == company["id"]
        )
        listing = client.get("/api/property/v1/communities").json()
        assert listing["total"] == 1 and listing["items"][0]["id"] == own["id"]
        assert client.get(f"/api/property/v1/communities/{outside['id']}").status_code == 404
        hidden = client.get(
            "/api/property/v1/communities", params={"property_company_id": other["id"]}
        ).json()
        assert hidden["items"] == [] and hidden["total"] == 0
        assert (
            client.patch(
                f"/api/platform/v1/property-companies/{company['id']}",
                json={"enabled": False},
                headers=platform_headers,
            ).status_code
            == 200
        )
        assert client.get("/api/property/v1/communities").status_code == 401
        assert (
            client.patch(
                f"/api/platform/v1/property-companies/{company['id']}",
                json={"enabled": True},
                headers=platform_headers,
            ).status_code
            == 200
        )
        assert client.get("/api/property/v1/admin-sessions/current").status_code == 401
