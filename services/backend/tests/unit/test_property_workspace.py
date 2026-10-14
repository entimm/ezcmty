from __future__ import annotations

from collections.abc import Generator, Iterator
from dataclasses import dataclass, replace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend_app.api.admin import get_admin_session_store
from backend_app.app_factory import create_app
from backend_app.core.admin_security import verify_password
from backend_app.core.errors import AppError
from backend_app.db.session import get_database_session
from backend_app.domain.admin.permissions import PermissionDefinition
from backend_app.models.admin import AdminAccount, AdminAuditLog
from backend_app.repositories.admin import AdminRepository
from backend_app.services.property_admin.admin import PropertyAdminService
from backend_app.services.property_admin.workspace import PropertyWorkspaceService
from tests.unit.test_admin import NEW_PASSWORD, ORIGIN, TEST_PASSWORD, Harness
from tests.unit.test_admin import harness as harness
from tests.unit.test_property import admin, company

PREFIX = "/api/property/v1"


@dataclass
class WorkspaceHarness:
    client: TestClient
    platform: Harness
    company_id: str
    account_id: str
    community_id: str

    def login(self, password: str = TEST_PASSWORD, name: str = "property_root") -> dict[str, Any]:
        response = self.client.post(
            f"{PREFIX}/admin-sessions",
            json={"login_name": name, "password": password},
            headers={"Origin": ORIGIN},
        )
        assert response.status_code == 201, response.text
        return dict(response.json())

    def headers(self) -> dict[str, str]:
        session = self.client.get(f"{PREFIX}/admin-sessions/current")
        assert session.status_code == 200, session.text
        return {"Origin": ORIGIN, "X-CSRF-Token": session.json()["csrf_token"]}

    def complete_login(self) -> None:
        self.login()
        response = self.client.post(
            f"{PREFIX}/admin-accounts/me/password-changes",
            json={"current_password": TEST_PASSWORD, "new_password": NEW_PASSWORD},
            headers=self.headers(),
        )
        assert response.status_code == 204, response.text
        self.login(NEW_PASSWORD)


def create_community(h: Harness, company_id: str, code: str) -> dict[str, Any]:
    response = h.client.post(
        "/v1/communities",
        json={
            "property_company_id": company_id,
            "code": code,
            "name": code,
            "address": "测试地址",
        },
        headers=h.headers(),
    )
    assert response.status_code == 201, response.text
    return dict(response.json())


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


def test_platform_provisioning_to_restricted_login_password_change_and_workspace(
    workspace: WorkspaceHarness,
) -> None:
    w = workspace
    assert w.client.get(f"{PREFIX}/property-companies/current").status_code == 401
    login = w.login()
    assert login["scope"] == "property_admin" and login["must_change_password"]
    assert login["permissions"] == []
    cookie = w.client.cookies.get("admin_session")
    assert cookie
    for path in (
        "/property-companies/current",
        "/communities",
        f"/communities/{w.community_id}",
        "/admin-accounts/me",
    ):
        response = w.client.get(PREFIX + path)
        assert response.status_code == 403
        assert response.json()["code"] == "auth.password_change_required"
    headers = w.headers()
    wrong = w.client.post(
        f"{PREFIX}/admin-accounts/me/password-changes",
        json={"current_password": "wrong-password", "new_password": NEW_PASSWORD},
        headers=headers,
    )
    assert wrong.status_code == 409 and wrong.json()["code"] == "auth.invalid_old_password"
    assert w.client.get(f"{PREFIX}/admin-sessions/current").status_code == 200
    changed = w.client.post(
        f"{PREFIX}/admin-accounts/me/password-changes",
        json={"current_password": TEST_PASSWORD, "new_password": NEW_PASSWORD},
        headers=headers,
    )
    assert changed.status_code == 204
    assert "Path=/api/property" in changed.headers["set-cookie"]
    assert w.client.get(f"{PREFIX}/admin-sessions/current").status_code == 401
    assert w.platform.store.read("property_admin", cookie) is None
    full = w.login(NEW_PASSWORD)
    assert not full["must_change_password"]
    assert set(full["permissions"]) == {"property.company.read", "property.community.read"}
    own = w.client.get(f"{PREFIX}/property-companies/current")
    assert own.status_code == 200 and own.json()["id"] == w.company_id
    assert own.json()["contact_name"] == "联系人"
    listing = w.client.get(f"{PREFIX}/communities").json()
    assert listing["total"] == 1 and listing["items"][0]["id"] == w.community_id
    profile = w.client.patch(
        f"{PREFIX}/admin-accounts/me", json={"display_name": "新显示名称"}, headers=w.headers()
    )
    assert profile.status_code == 200 and profile.json()["display_name"] == "新显示名称"
    assert w.client.get(f"{PREFIX}/admin-sessions/current").json()["display_name"] == "新显示名称"
    assert w.platform.client.get("/v1/admin-sessions/current").status_code == 200
    with w.platform.factory() as db:
        entries = list(
            db.scalars(select(AdminAuditLog).where(AdminAuditLog.scope == "property_admin"))
        )
        assert {entry.action for entry in entries} >= {
            "session.login",
            "account.password_change",
            "account.profile_update",
        }
        assert all(entry.property_company_id == w.company_id for entry in entries)
        assert all(TEST_PASSWORD not in str(entry.safe_metadata) for entry in entries)


def test_company_scope_filters_counts_pagination_and_hidden_details(
    workspace: WorkspaceHarness,
) -> None:
    w = workspace
    own_second = create_community(w.platform, w.company_id, "second-community")
    stopped = w.platform.client.patch(
        f"/v1/communities/{own_second['id']}", json={"enabled": False}, headers=w.platform.headers()
    )
    assert stopped.status_code == 200
    other = company(w.platform, "other")
    outside = create_community(w.platform, other["id"], "outside-community")
    w.complete_login()
    first = w.client.get(f"{PREFIX}/communities", params={"page_size": 1}).json()
    second = w.client.get(f"{PREFIX}/communities", params={"page_size": 1, "page": 2}).json()
    assert first["total"] == second["total"] == 2
    assert {first["items"][0]["id"], second["items"][0]["id"]} == {w.community_id, own_second["id"]}
    for company_id in (other["id"], "019a0000-0000-7000-8000-000000000001"):
        filtered = w.client.get(
            f"{PREFIX}/communities", params={"property_company_id": company_id}
        ).json()
        assert filtered["items"] == [] and filtered["total"] == 0
    own = w.client.get(f"{PREFIX}/communities", params={"property_company_id": w.company_id}).json()
    assert own["total"] == 2
    disabled = w.client.get(f"{PREFIX}/communities", params={"enabled": False}).json()
    assert disabled["total"] == 1 and disabled["items"][0]["id"] == own_second["id"]
    assert w.client.get(f"{PREFIX}/communities/{own_second['id']}").status_code == 200
    for community_id in (outside["id"], "019a0000-0000-7000-8000-000000000001"):
        response = w.client.get(f"{PREFIX}/communities/{community_id}")
        assert response.status_code == 404 and response.json()["code"] == "resource.not_found"
    assert w.client.get(f"{PREFIX}/communities", params={"code": "first"}).json()["total"] == 1


def test_login_scope_and_company_inputs_cannot_be_selected(workspace: WorkspaceHarness) -> None:
    w = workspace
    for field, value in (("scope", "platform_admin"), ("property_company_id", w.company_id)):
        login = w.client.post(
            f"{PREFIX}/admin-sessions",
            json={"login_name": "property_root", "password": TEST_PASSWORD, field: value},
            headers={"Origin": ORIGIN},
        )
        assert login.status_code == 422
    w.complete_login()
    forged = w.client.patch(
        f"{PREFIX}/admin-accounts/me",
        json={"display_name": "改名", "property_company_id": w.company_id},
        headers=w.headers(),
    )
    assert forged.status_code == 422
    platform_cookie = w.platform.client.cookies.get("admin_session")
    property_cookie = w.client.cookies.get("admin_session")
    assert platform_cookie and property_cookie
    assert (
        w.client.get(
            f"{PREFIX}/admin-sessions/current",
            headers={"Cookie": f"admin_session={platform_cookie}"},
        ).status_code
        == 401
    )
    assert (
        w.platform.client.get(
            "/v1/admin-sessions/current", headers={"Cookie": f"admin_session={property_cookie}"}
        ).status_code
        == 401
    )
    assert w.platform.client.get("/v1/admin-sessions/current").status_code == 200


def test_disabled_company_and_account_login_fail_uniformly(workspace: WorkspaceHarness) -> None:
    w = workspace
    admin(w.platform, w.company_id, "second-admin")
    account_path = f"/v1/property-companies/{w.company_id}/admin-accounts/{w.account_id}"
    responses = []
    for name, password in (("missing", TEST_PASSWORD), ("property_root", "wrong-password")):
        responses.append(
            w.client.post(
                f"{PREFIX}/admin-sessions",
                json={"login_name": name, "password": password},
                headers={"Origin": ORIGIN},
            )
        )
    disabled = w.platform.client.patch(
        account_path, json={"enabled": False}, headers=w.platform.headers()
    )
    assert disabled.status_code == 200
    responses.append(
        w.client.post(
            f"{PREFIX}/admin-sessions",
            json={"login_name": "property_root", "password": TEST_PASSWORD},
            headers={"Origin": ORIGIN},
        )
    )
    assert (
        w.platform.client.patch(
            account_path, json={"enabled": True}, headers=w.platform.headers()
        ).status_code
        == 200
    )
    assert (
        w.platform.client.patch(
            f"/v1/property-companies/{w.company_id}",
            json={"enabled": False},
            headers=w.platform.headers(),
        ).status_code
        == 200
    )
    responses.append(
        w.client.post(
            f"{PREFIX}/admin-sessions",
            json={"login_name": "property_root", "password": TEST_PASSWORD},
            headers={"Origin": ORIGIN},
        )
    )
    assert all(
        r.status_code == 401 and r.json()["code"] == "auth.invalid_credentials" for r in responses
    )
    assert len({r.json()["detail"] for r in responses}) == 1


def test_company_and_account_reenable_and_password_reset_never_restore_old_sessions(
    workspace: WorkspaceHarness,
) -> None:
    w = workspace
    w.complete_login()
    first = w.client.cookies.get("admin_session")
    w.login(NEW_PASSWORD)
    second = w.client.cookies.get("admin_session")
    assert first and second and first != second
    company_path = f"/v1/property-companies/{w.company_id}"
    assert (
        w.platform.client.patch(
            company_path, json={"enabled": False}, headers=w.platform.headers()
        ).status_code
        == 200
    )
    assert w.platform.store.read("property_admin", first) is not None
    assert w.client.get(f"{PREFIX}/communities").status_code == 401
    assert (
        w.platform.client.patch(
            company_path, json={"enabled": True}, headers=w.platform.headers()
        ).status_code
        == 200
    )
    assert w.client.get(f"{PREFIX}/communities").status_code == 401
    for token in (first, second):
        assert (
            w.client.get(
                f"{PREFIX}/admin-sessions/current", headers={"Cookie": f"admin_session={token}"}
            ).status_code
            == 401
        )
    w.login(NEW_PASSWORD)
    admin(w.platform, w.company_id, "second-admin")
    account_path = f"{company_path}/admin-accounts/{w.account_id}"
    for enabled in (False, True):
        assert (
            w.platform.client.patch(
                account_path, json={"enabled": enabled}, headers=w.platform.headers()
            ).status_code
            == 200
        )
        assert w.client.get(f"{PREFIX}/admin-accounts/me").status_code == 401
    w.login(NEW_PASSWORD)
    assert (
        w.platform.client.post(
            account_path + "/password-resets",
            json={"password": TEST_PASSWORD},
            headers=w.platform.headers(),
        ).status_code
        == 204
    )
    assert w.client.get(f"{PREFIX}/communities").status_code == 401
    reset_login = w.login()
    assert reset_login["must_change_password"] and reset_login["permissions"] == []
    assert w.client.get(f"{PREFIX}/property-companies/current").status_code == 403


def test_password_change_revokes_other_devices_but_logout_is_current_only(
    workspace: WorkspaceHarness,
) -> None:
    w = workspace
    w.complete_login()
    other = w.client.cookies.get("admin_session")
    w.login(NEW_PASSWORD)
    assert other
    assert (
        w.client.delete(f"{PREFIX}/admin-sessions/current", headers=w.headers()).status_code == 204
    )
    assert w.client.get(f"{PREFIX}/admin-sessions/current").status_code == 401
    assert (
        w.client.get(
            f"{PREFIX}/admin-sessions/current", headers={"Cookie": f"admin_session={other}"}
        ).status_code
        == 200
    )
    w.login(NEW_PASSWORD)
    assert (
        w.client.post(
            f"{PREFIX}/admin-accounts/me/password-changes",
            json={"current_password": NEW_PASSWORD, "new_password": TEST_PASSWORD},
            headers=w.headers(),
        ).status_code
        == 204
    )
    assert (
        w.client.get(
            f"{PREFIX}/admin-sessions/current", headers={"Cookie": f"admin_session={other}"}
        ).status_code
        == 401
    )


def test_write_origin_csrf_and_property_login_rate_limit(workspace: WorkspaceHarness) -> None:
    w = workspace
    rejected = w.client.post(
        f"{PREFIX}/admin-sessions", json={"login_name": "property_root", "password": TEST_PASSWORD}
    )
    assert rejected.status_code == 403 and rejected.json()["code"] == "auth.csrf_failed"
    w.login()
    for headers in (
        {"Origin": ORIGIN},
        {"Origin": "https://evil.test", "X-CSRF-Token": w.headers()["X-CSRF-Token"]},
    ):
        denied = w.client.post(
            f"{PREFIX}/admin-accounts/me/password-changes",
            json={"current_password": TEST_PASSWORD, "new_password": NEW_PASSWORD},
            headers=headers,
        )
        assert denied.status_code == 403 and denied.json()["code"] == "auth.csrf_failed"
    w.platform.store.settings.admin_login_limit = 2
    attempts = [
        w.client.post(
            f"{PREFIX}/admin-sessions",
            json={"login_name": "rate-limited", "password": TEST_PASSWORD},
            headers={"Origin": ORIGIN},
        )
        for _ in range(2)
    ]
    assert attempts[-1].status_code == 429 and attempts[-1].json()["code"] == "auth.rate_limited"
    assert w.platform.client.get("/v1/admin-sessions/current").status_code == 200


def test_workspace_permissions_and_missing_company_fail_closed(
    workspace: WorkspaceHarness,
    monkeypatch: MonkeyPatch,
) -> None:
    w = workspace
    w.complete_login()
    monkeypatch.setattr(
        "backend_app.domain.admin.identity.permission_catalog",
        lambda scope: (
            [
                PermissionDefinition(
                    code="property.company.read", name="公司", group="公司", assignable=True
                )
            ]
            if scope == "property_admin"
            else []
        ),
    )
    assert w.client.get(f"{PREFIX}/property-companies/current").status_code == 200
    assert w.client.get(f"{PREFIX}/communities").status_code == 403
    token = w.client.cookies.get("admin_session")
    assert token
    with w.platform.factory() as db:
        ctx = PropertyAdminService(db).authenticate(w.platform.store, token)
        service = PropertyWorkspaceService(db)
        for invalid in (
            replace(ctx, property_company_id=None),
            replace(ctx, scope="platform_admin"),
        ):
            with pytest.raises(AppError) as caught:
                service.get_current_company(invalid)
            assert caught.value.code == "auth.forbidden"


def test_failed_audit_rolls_back_property_password_change(
    workspace: WorkspaceHarness,
    monkeypatch: MonkeyPatch,
) -> None:
    w = workspace
    w.login()
    headers = w.headers()

    def fail(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("audit storage failed")

    monkeypatch.setattr(AdminRepository, "audit", fail)
    response = w.client.post(
        f"{PREFIX}/admin-accounts/me/password-changes",
        json={"current_password": TEST_PASSWORD, "new_password": NEW_PASSWORD},
        headers=headers,
    )
    assert response.status_code == 500
    with w.platform.factory() as db:
        account = db.get(AdminAccount, w.account_id)
        assert account and account.must_change_password and account.session_version == 1
        assert verify_password(account.password_hash, TEST_PASSWORD)
    assert w.client.get(f"{PREFIX}/admin-sessions/current").status_code == 200
