from tests.support.admin import Harness, company
from tests.support.housing import create_house, create_node, housing_path, set_permissions
from tests.support.workspace import PREFIX, WorkspaceHarness

from backend_app.models.admin import AdminRole
from backend_app.repositories.admin import AdminRepository


def platform_permissions(harness: Harness, permissions: set[str]) -> None:
    account_id = harness.client.get("/v1/admin-sessions/current").json()["subject_id"]
    with harness.factory() as db:
        repo = AdminRepository(db, "platform_admin")
        role = repo.role_by_code("business_reader")
        if role is None:
            role = AdminRole(
                scope="platform_admin", code="business_reader", name="业务角色", enabled=True
            )
            db.add(role)
            db.flush()
        repo.replace_permissions(role.id, permissions)
        repo.replace_roles(account_id, {role.id})
        db.commit()


def test_basic_context_does_not_require_or_grant_business_reading(
    workspace: WorkspaceHarness,
) -> None:
    workspace.complete_login()
    other = company(workspace.platform, "outside-context")
    set_permissions(workspace, set())
    context = workspace.client.get(f"{PREFIX}/property-workspace/context")
    assert context.status_code == 200, context.text
    assert context.json() == {
        "property_company_id": workspace.company_id,
        "property_company_name": "company",
    }
    options = workspace.client.get(f"{PREFIX}/community-options")
    assert options.status_code == 200, options.text
    assert options.json()["total"] == 1
    assert set(options.json()["items"][0]) == {"id", "property_company_id", "name", "enabled"}
    foreign = workspace.client.get(
        f"{PREFIX}/community-options", params={"property_company_id": other["id"]}
    )
    assert foreign.status_code == 200 and foreign.json()["total"] == 0
    for path in ("/property-companies/current", "/communities"):
        assert workspace.client.get(PREFIX + path).status_code == 403


def test_bill_reader_can_locate_houses_without_reading_property_or_owner_files(
    workspace: WorkspaceHarness,
) -> None:
    workspace.complete_login()
    node = create_node(workspace)
    house = create_house(
        workspace, node["id"], owners=[{"name": "不应返回的业主", "phone": "13800138000"}]
    )
    create_house(workspace, node["id"], room_no="102")
    set_permissions(workspace, {"property.bill.read"})
    response = workspace.client.get(
        housing_path(workspace, "/house-options"), params={"house_id": house["id"]}
    )
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 1
    item = response.json()["items"][0]
    assert item["id"] == house["id"] and "101" in item["label"]
    assert set(item) == {"id", "community_id", "label", "enabled", "effective_enabled"}
    assert "不应返回的业主" not in response.text and "13800138000" not in response.text
    assert workspace.client.get(housing_path(workspace, "/houses")).status_code == 403
    assert (
        workspace.client.get(housing_path(workspace, f"/houses/{house['id']}/owners")).status_code
        == 403
    )


def test_platform_system_reader_uses_minimal_company_selection_without_onboarding_access(
    workspace: WorkspaceHarness,
) -> None:
    harness = workspace.platform
    platform_permissions(harness, {"platform.system.read"})
    options = harness.client.get(
        "/v1/property-company-options", params={"property_company_id": workspace.company_id}
    )
    assert options.status_code == 200, options.text
    assert options.json()["total"] == 1
    assert set(options.json()["items"][0]) == {"id", "name", "enabled"}
    assert harness.client.get(f"/v1/property-companies/{workspace.company_id}").status_code == 403
    accounts = harness.client.get(f"/v1/property-companies/{workspace.company_id}/admin-accounts")
    assert accounts.status_code == 200, accounts.text
    assert accounts.json()["items"][0]["effective_permissions"]


def test_company_state_and_profile_require_independent_permissions(
    workspace: WorkspaceHarness,
) -> None:
    harness = workspace.platform
    path = f"/v1/property-companies/{workspace.company_id}"
    platform_permissions(harness, {"platform.onboarding.manage"})
    result = harness.client.patch(path, json={"name": "资料可维护"}, headers=harness.headers())
    assert result.status_code == 200, result.text
    assert (
        harness.client.patch(path, json={"enabled": False}, headers=harness.headers()).status_code
        == 403
    )
    platform_permissions(harness, {"platform.onboarding.toggle"})
    rejected = harness.client.patch(
        path, json={"enabled": False, "name": "不能混入资料修改"}, headers=harness.headers()
    )
    assert rejected.status_code == 403
    result = harness.client.patch(path, json={"enabled": False}, headers=harness.headers())
    assert result.status_code == 200 and not result.json()["enabled"]
