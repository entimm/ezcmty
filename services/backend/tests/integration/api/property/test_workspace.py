from __future__ import annotations

from dataclasses import replace

import pytest
from pytest import MonkeyPatch
from sqlalchemy import select
from tests.support.admin import NEW_PASSWORD, TEST_PASSWORD, company
from tests.support.workspace import PREFIX, WorkspaceHarness, create_community

from backend_app.core.errors import AppError
from backend_app.domain.admin.permissions import PermissionDefinition
from backend_app.models.admin import AdminAuditLog
from backend_app.services.property_admin.admin import PropertyAdminService
from backend_app.services.property_admin.workspace import PropertyWorkspaceService


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
        f"/communities/{w.community_id}/space-nodes",
        f"/communities/{w.community_id}/houses",
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
    assert set(full["permissions"]) == {
        "property.company.read",
        "property.house_claim.read",
        "property.house_claim.review",
        "property.resident_house_binding.read",
        "property.resident_house_binding.revoke",
        "property.community.read",
        "property.space.read",
        "property.space.create",
        "property.space.update",
        "property.house.read",
        "property.house.create",
        "property.house.update",
        "property.house_owner.read",
        "property.house_owner.create",
        "property.house_owner.update",
        "property.fee_basis.read",
        "property.fee_basis.create",
        "property.bill.read",
        "property.bill.create",
        "property.bill.update",
        "property.bill.void",
        "property.bill_receipt.create",
        "property.bill_receipt.correct",
    }
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
