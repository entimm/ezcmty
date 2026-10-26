import pytest
from sqlalchemy import func, select
from tests.support.housing import housing_path, set_permissions
from tests.support.workspace import PREFIX, WorkspaceHarness

from backend_app.models.admin import AdminAccount
from backend_app.models.housing import SpaceNode
from backend_app.models.property import Community, PropertyCompany


def test_prepared_sessions_keep_cookie_paths_scope_and_logout_independent(
    business_workspace: WorkspaceHarness,
) -> None:
    workspace = business_workspace
    platform = workspace.platform
    platform_token = platform.client.cookies.get("admin_session")
    property_token = workspace.client.cookies.get("admin_session")
    assert platform_token and property_token and platform_token != property_token
    assert {cookie.path for cookie in platform.client.cookies.jar} == {"/api/platform"}
    assert {cookie.path for cookie in workspace.client.cookies.jar} == {"/api/property"}
    assert platform.client.get("/v1/admin-sessions/current").status_code == 200
    assert workspace.client.get(f"{PREFIX}/admin-sessions/current").status_code == 200
    for client, path, token in (
        (platform.client, "/v1/admin-sessions/current", property_token),
        (workspace.client, f"{PREFIX}/admin-sessions/current", platform_token),
    ):
        refused = client.get(path, headers={"Cookie": f"admin_session={token}"})
        assert refused.status_code == 401 and refused.json()["code"] == "auth.unauthenticated"
    logged_out = workspace.client.delete(
        f"{PREFIX}/admin-sessions/current", headers=workspace.headers()
    )
    assert logged_out.status_code == 204
    assert workspace.client.get(f"{PREFIX}/admin-sessions/current").status_code == 401
    assert platform.client.get("/v1/admin-sessions/current").status_code == 200


@pytest.mark.parametrize("invalid", ["origin", "missing-csrf", "wrong-csrf"])
def test_prepared_business_writes_still_require_origin_and_csrf(
    business_workspace: WorkspaceHarness, invalid: str
) -> None:
    workspace = business_workspace
    headers = workspace.headers()
    if invalid == "origin":
        headers["Origin"] = "https://untrusted.example"
    elif invalid == "missing-csrf":
        headers.pop("X-CSRF-Token")
    else:
        headers["X-CSRF-Token"] = "incorrect-csrf"
    path = housing_path(workspace, "/space-nodes")
    body = {"node_type": "building", "name": "业务楼栋"}
    refused = workspace.client.post(path, json=body, headers=headers)
    assert refused.status_code == 403 and refused.json()["code"] == "auth.csrf_failed"
    with workspace.platform.factory() as db:
        assert db.scalar(select(func.count()).select_from(SpaceNode)) == 0
    assert workspace.client.post(path, json=body, headers=workspace.headers()).status_code == 201


def test_prepared_business_session_reloads_permissions_and_hides_other_tenant(
    business_workspace: WorkspaceHarness,
) -> None:
    workspace = business_workspace
    with workspace.platform.factory() as db:
        other = PropertyCompany(code="OTHER", name="其他物业", enabled=True)
        db.add(other)
        db.flush()
        outside = Community(
            property_company_id=other.id, code="OTHER-COMMUNITY", name="其他小区", address="地址"
        )
        db.add(outside)
        db.commit()
        outside_id = outside.id
    set_permissions(workspace, {"property.housing.read"})
    path = housing_path(workspace, "/space-nodes")
    assert workspace.client.get(path).status_code == 200
    refused = workspace.client.post(
        path,
        json={"node_type": "building", "name": "权限不足"},
        headers=workspace.headers(),
    )
    assert refused.status_code == 403 and refused.json()["code"] == "auth.forbidden"
    hidden = workspace.client.get(f"{PREFIX}/communities/{outside_id}/space-nodes")
    assert hidden.status_code == 404 and hidden.json()["code"] == "resource.not_found"


@pytest.mark.parametrize("invalid", ["account", "version", "company", "session"])
def test_prepared_business_session_still_obeys_live_identity_state(
    business_workspace: WorkspaceHarness, invalid: str
) -> None:
    workspace = business_workspace
    path = f"{PREFIX}/admin-sessions/current"
    assert workspace.client.get(path).status_code == 200
    if invalid == "session":
        token = workspace.client.cookies.get("admin_session")
        assert token
        workspace.platform.store.delete("property_admin", token)
    else:
        with workspace.platform.factory() as db:
            account = db.get(AdminAccount, workspace.account_id)
            company = db.get(PropertyCompany, workspace.company_id)
            assert account and company
            if invalid == "account":
                account.enabled = False
            elif invalid == "version":
                account.session_version += 1
            else:
                company.enabled = False
            db.commit()
    refused = workspace.client.get(path)
    assert refused.status_code == 401 and refused.json()["code"] == "auth.unauthenticated"
