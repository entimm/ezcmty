import json
from typing import Any

import pytest
from sqlalchemy import func, select
from tests.support.admin import company
from tests.support.housing import create_house, create_node, housing_path, set_permissions
from tests.support.workspace import PREFIX, WorkspaceHarness, create_community

from backend_app.models.admin import AdminAuditLog
from backend_app.models.housing import House, HouseOwner


def test_hierarchy_subtree_filters_paths_and_empty_page_total(
    business_workspace: WorkspaceHarness,
) -> None:
    workspace = business_workspace
    phase = create_node(workspace, "东区", "phase")
    building = create_node(workspace, parent_id=phase["id"])
    unit = create_node(workspace, "一单元", "unit", building["id"])
    other = create_node(workspace, "2号楼")
    first = create_house(workspace, unit["id"], floor_no=-1, external_code=" 00a ")
    second = create_house(workspace, building["id"], "B01")
    create_house(workspace, other["id"])
    assert first["external_code"] == "00a"
    assert first["display_address"] == "first-community／东区／1号楼／一单元／101"
    detail = workspace.client.get(housing_path(workspace, f"/space-nodes/{unit['id']}")).json()
    assert [item["id"] for item in detail["ancestors"]] == [phase["id"], building["id"]]
    root = workspace.client.get(housing_path(workspace, "/space-nodes")).json()
    assert root["total"] == 2 and root["items"][0]["has_children"]
    for selected in (phase, building):
        page = workspace.client.get(
            housing_path(workspace, "/houses"),
            params={"space_node_id": selected["id"], "sort": "created_at"},
        ).json()
        assert [item["id"] for item in page["items"]] == [first["id"], second["id"]]
    exact = workspace.client.get(
        housing_path(workspace, "/houses"),
        params={
            "space_node_id": phase["id"],
            "room_no": "101",
            "floor_no": -1,
            "external_code": "00a",
            "enabled": True,
        },
    ).json()
    assert exact["total"] == 1 and exact["items"][0]["id"] == first["id"]
    assert (
        workspace.client.get(
            housing_path(workspace, "/houses"), params={"external_code": "00A"}
        ).json()["total"]
        == 0
    )
    empty = workspace.client.get(
        housing_path(workspace, "/houses"),
        params={"space_node_id": phase["id"], "page": 9, "page_size": 1},
    ).json()
    assert empty == {"items": [], "total": 2, "page": 9, "page_size": 1}
    nodes = workspace.client.get(housing_path(workspace, "/space-nodes"), params={"page": 9}).json()
    assert nodes["items"] == [] and nodes["total"] == 2


def test_house_owners_normalization_atomicity_audit_and_plaintext_storage(
    business_workspace: WorkspaceHarness,
) -> None:
    workspace = business_workspace
    building = create_node(workspace)
    owners = [
        {"name": " 张甲 ", "phone": "+8613800000000"},
        {"name": "李乙", "phone": "008613900000000"},
    ]
    house = create_house(workspace, building["id"], owners=owners)
    assert "owners" not in house and "phone" not in json.dumps(house)
    url = housing_path(workspace, f"/houses/{house['id']}/owners")
    listing = workspace.client.get(url).json()
    assert listing["total"] == 2
    assert {(item["name"], item["phone"]) for item in listing["items"]} == {
        ("张甲", "13800000000"),
        ("李乙", "13900000000"),
    }
    owner = listing["items"][0]
    assert workspace.client.get(f"{url}/{owner['id']}").json() == owner
    empty = workspace.client.get(url, params={"page": 99}).json()
    assert empty["total"] == 2 and empty["items"] == []
    with workspace.platform.factory() as db:
        stored = db.get(HouseOwner, owner["id"])
        assert stored and stored.phone == owner["phone"]
        logs = list(
            db.scalars(select(AdminAuditLog).where(AdminAuditLog.action.like("property.house%")))
        )
        assert len(logs) == 3
        assert all(
            log.scope == "property_admin" and log.property_company_id == workspace.company_id
            for log in logs
        )
        audit = json.dumps([log.safe_metadata for log in logs])
        assert owner["name"] not in audit and owner["phone"] not in audit
    duplicate = workspace.client.post(
        housing_path(workspace, "/houses"),
        json={
            "space_node_id": building["id"],
            "room_no": "102",
            "owners": [owners[0], {"name": "张甲", "phone": "13800000000"}],
        },
        headers=workspace.headers(),
    )
    assert (
        duplicate.status_code == 409
        and duplicate.json()["code"] == "property.duplicate_house_owner"
    )
    with workspace.platform.factory() as db:
        assert db.scalar(select(func.count()).select_from(House)) == 1
        assert db.scalar(select(func.count()).select_from(HouseOwner)) == 2
        assert (
            db.scalar(
                select(func.count())
                .select_from(AdminAuditLog)
                .where(AdminAuditLog.action.like("property.house%"))
            )
            == 3
        )


def test_disable_preserves_descendant_state_and_allows_corrections(
    business_workspace: WorkspaceHarness,
) -> None:
    workspace = business_workspace
    building = create_node(workspace)
    unit = create_node(workspace, "一单元", "unit", building["id"])
    house = create_house(workspace, unit["id"], owners=[{"name": "业主", "phone": "13800000000"}])
    url = housing_path(workspace, f"/houses/{house['id']}")
    owner = workspace.client.get(f"{url}/owners").json()["items"][0]
    assert (
        workspace.client.patch(
            housing_path(workspace, f"/space-nodes/{building['id']}"),
            json={"enabled": False},
            headers=workspace.headers(),
        ).status_code
        == 200
    )
    for suffix in (
        f"/space-nodes/{unit['id']}",
        f"/houses/{house['id']}",
        f"/houses/{house['id']}/owners/{owner['id']}",
    ):
        item = workspace.client.get(housing_path(workspace, suffix)).json()
        assert item["enabled"] and not item["effective_enabled"]
    for suffix, body in (
        ("/space-nodes", {"parent_id": building["id"], "node_type": "unit", "name": "二单元"}),
        ("/houses", {"space_node_id": unit["id"], "room_no": "102"}),
        (f"/houses/{house['id']}/owners", {"name": "新业主", "phone": "13900000000"}),
    ):
        response = workspace.client.post(
            housing_path(workspace, suffix), json=body, headers=workspace.headers()
        )
        assert (
            response.status_code == 409 and response.json()["code"] == "property.housing_disabled"
        )
    corrected = workspace.client.patch(
        url, json={"external_code": " 00B ", "floor_no": -2}, headers=workspace.headers()
    )
    assert corrected.status_code == 200 and not corrected.json()["effective_enabled"]
    assert (
        workspace.client.patch(
            f"{url}/owners/{owner['id']}",
            json={"name": "姓名纠错", "phone": "+8613900000000"},
            headers=workspace.headers(),
        ).status_code
        == 200
    )
    cleared = workspace.client.patch(
        url, json={"external_code": " ", "floor_no": None}, headers=workspace.headers()
    ).json()
    assert cleared["external_code"] is None and cleared["floor_no"] is None
    workspace.client.patch(
        housing_path(workspace, f"/space-nodes/{building['id']}"),
        json={"enabled": True},
        headers=workspace.headers(),
    )
    assert workspace.client.get(url).json()["effective_enabled"]


@pytest.mark.parametrize(
    "suffix,body",
    [("space-nodes", {"node_type": "unit", "name": "错误根节点"}), ("houses", {"room_no": "101"})],
)
def test_invalid_parent_types(
    business_workspace: WorkspaceHarness, suffix: str, body: dict[str, Any]
) -> None:
    workspace = business_workspace
    if suffix == "houses":
        phase = create_node(workspace, "分区", "phase")
        body["space_node_id"] = phase["id"]
    result = workspace.client.post(
        housing_path(workspace, f"/{suffix}"), json=body, headers=workspace.headers()
    )
    assert result.status_code == 409


@pytest.mark.parametrize(
    "entity,patch",
    [
        ("node", {}),
        ("house", {}),
        ("owner", {}),
        ("node", {"parent_id": None}),
        ("node", {"node_type": "unit"}),
        ("house", {"space_node_id": None}),
        ("house", {"owners": []}),
        ("owner", {"house_id": None}),
        ("house", {"room_no": None}),
        ("owner", {"phone": None}),
        ("node", {"enabled": None}),
    ],
)
def test_updates_reject_empty_fixed_and_null_fields(
    business_workspace: WorkspaceHarness, entity: str, patch: dict[str, Any]
) -> None:
    workspace = business_workspace
    node = create_node(workspace)
    house = create_house(workspace, node["id"], owners=[{"name": "业主", "phone": "13800000000"}])
    owner = workspace.client.get(housing_path(workspace, f"/houses/{house['id']}/owners")).json()[
        "items"
    ][0]
    paths = {
        "node": f"/space-nodes/{node['id']}",
        "house": f"/houses/{house['id']}",
        "owner": f"/houses/{house['id']}/owners/{owner['id']}",
    }
    response = workspace.client.patch(
        housing_path(workspace, paths[entity]), json=patch, headers=workspace.headers()
    )
    assert response.status_code == 422, response.text


def test_duplicate_names_rooms_and_owner_contacts_include_disabled_rows(
    business_workspace: WorkspaceHarness,
) -> None:
    workspace = business_workspace
    node = create_node(workspace)
    house = create_house(workspace, node["id"], owners=[{"name": "业主", "phone": "13800000000"}])
    owner_path = housing_path(workspace, f"/houses/{house['id']}/owners")
    owner = workspace.client.get(owner_path).json()["items"][0]
    for path, body in (
        (f"{owner_path}/{owner['id']}", {"enabled": False}),
        (housing_path(workspace, f"/houses/{house['id']}"), {"enabled": False}),
        (housing_path(workspace, f"/space-nodes/{node['id']}"), {"enabled": False}),
    ):
        assert (
            workspace.client.patch(path, json=body, headers=workspace.headers()).status_code == 200
        )
    duplicate = workspace.client.post(
        housing_path(workspace, "/space-nodes"),
        json={"node_type": "phase", "name": node["name"]},
        headers=workspace.headers(),
    )
    assert (
        duplicate.status_code == 409 and duplicate.json()["code"] == "property.duplicate_space_name"
    )
    workspace.client.patch(
        housing_path(workspace, f"/space-nodes/{node['id']}"),
        json={"enabled": True},
        headers=workspace.headers(),
    )
    duplicate = workspace.client.post(
        housing_path(workspace, "/houses"),
        json={"space_node_id": node["id"], "room_no": "101"},
        headers=workspace.headers(),
    )
    assert duplicate.status_code == 409 and duplicate.json()["code"] == "property.duplicate_room_no"
    workspace.client.patch(
        housing_path(workspace, f"/houses/{house['id']}"),
        json={"enabled": True},
        headers=workspace.headers(),
    )
    duplicate = workspace.client.post(
        owner_path, json={"name": "业主", "phone": "008613800000000"}, headers=workspace.headers()
    )
    assert (
        duplicate.status_code == 409
        and duplicate.json()["code"] == "property.duplicate_house_owner"
    )


def test_company_community_and_house_nested_scope(business_workspace: WorkspaceHarness) -> None:
    workspace = business_workspace
    node = create_node(workspace)
    house = create_house(workspace, node["id"], owners=[{"name": "业主", "phone": "13800000000"}])
    owner = workspace.client.get(housing_path(workspace, f"/houses/{house['id']}/owners")).json()[
        "items"
    ][0]
    other_house = create_house(workspace, node["id"], "102")
    other_community = create_community(workspace.platform, workspace.company_id, "SECOND")
    outside_company = company(workspace.platform, "outside")
    outside = create_community(workspace.platform, outside_company["id"], "OUTSIDE")
    for community in (other_community, outside):
        base = f"{PREFIX}/communities/{community['id']}"
        for suffix in (
            f"/space-nodes/{node['id']}",
            f"/houses/{house['id']}",
            f"/houses/{house['id']}/owners/{owner['id']}",
        ):
            assert workspace.client.get(base + suffix).status_code == 404
        response = workspace.client.post(
            base + "/houses",
            json={"space_node_id": node["id"], "room_no": "101"},
            headers=workspace.headers(),
        )
        assert response.status_code == 404
    assert (
        workspace.client.get(
            housing_path(workspace, f"/houses/{other_house['id']}/owners/{owner['id']}")
        ).status_code
        == 404
    )
    assert (
        workspace.client.get(
            housing_path(workspace, "/houses"), params={"space_node_id": outside["id"]}
        ).status_code
        == 404
    )


def test_property_maintenance_covers_house_owner_and_space_operations(
    business_workspace: WorkspaceHarness,
) -> None:
    workspace = business_workspace
    node = create_node(workspace)
    house = create_house(workspace, node["id"], owners=[{"name": "业主", "phone": "13800000000"}])
    set_permissions(workspace, {"property.housing.manage", "property.housing.read"})
    assert (
        workspace.client.get(housing_path(workspace, f"/houses/{house['id']}")).status_code == 200
    )
    assert (
        workspace.client.get(housing_path(workspace, f"/houses/{house['id']}/owners")).status_code
        == 200
    )
    assert workspace.client.get(housing_path(workspace, "/space-nodes")).status_code == 200
    create_house(workspace, node["id"], "102")
    created = workspace.client.post(
        housing_path(workspace, "/houses"),
        json={
            "space_node_id": node["id"],
            "room_no": "103",
            "owners": [{"name": "业主", "phone": "13800000000"}],
        },
        headers=workspace.headers(),
    )
    assert created.status_code == 201
    assert workspace.client.get(housing_path(workspace, "/houses")).json()["total"] == 3


def test_housing_writes_require_csrf_and_hide_invalid_owner_input(
    business_workspace: WorkspaceHarness, caplog: pytest.LogCaptureFixture
) -> None:
    workspace = business_workspace
    node = create_node(workspace)
    body = {"space_node_id": node["id"], "room_no": "101"}
    assert workspace.client.post(housing_path(workspace, "/houses"), json=body).status_code == 403
    response = workspace.client.post(
        housing_path(workspace, "/houses"),
        json={**body, "owners": [{"name": "隐私姓名", "phone": "invalid-private-phone"}]},
        headers=workspace.headers(),
    )
    assert response.status_code == 422
    assert "invalid-private-phone" not in response.text + caplog.text
    assert "隐私姓名" not in response.text + caplog.text
