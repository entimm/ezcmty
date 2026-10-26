import json

import pytest
from sqlalchemy import func, select
from tests.support.housing import create_house, create_node, housing_path
from tests.support.workspace import WorkspaceHarness

from backend_app.core.errors import AppError
from backend_app.domain.housing import HouseOwnerCreationCommand
from backend_app.models.admin import AdminAuditLog
from backend_app.models.housing import HouseOwner
from backend_app.services.house_owner_creation import (
    create_house_owner,
    prepare_house_owner_creation,
)


def test_manual_owner_creation_normalizes_and_keeps_duplicate_conflict(
    business_workspace: WorkspaceHarness,
) -> None:
    workspace = business_workspace
    building = create_node(workspace)
    house = create_house(workspace, building["id"])
    url = housing_path(workspace, f"/houses/{house['id']}/owners")
    body = {"name": " 张甲 ", "phone": " 008613800000000 "}
    created = workspace.client.post(url, json=body, headers=workspace.headers())
    assert created.status_code == 201, created.text
    owner = created.json()
    assert (owner["name"], owner["phone"], owner["enabled"]) == ("张甲", "13800000000", True)
    duplicate = workspace.client.post(url, json=body, headers=workspace.headers())
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "property.duplicate_house_owner"
    with workspace.platform.factory() as db:
        logs = list(
            db.scalars(
                select(AdminAuditLog).where(AdminAuditLog.action == "property.house_owner.create")
            )
        )
        assert len(logs) == 1
        assert logs[0].target_id == owner["id"]
        assert logs[0].safe_metadata == {"changed_fields": ["name", "phone"]}
        assert owner["name"] not in json.dumps(logs[0].safe_metadata)
        assert owner["phone"] not in json.dumps(logs[0].safe_metadata)


def test_shared_registration_and_audit_participate_in_caller_rollback(
    business_workspace: WorkspaceHarness,
) -> None:
    workspace = business_workspace
    house = create_house(workspace, create_node(workspace)["id"])
    command = HouseOwnerCreationCommand(house["id"], " 张甲 ", "+8613800000000")
    with workspace.platform.factory() as db:
        prepared = prepare_house_owner_creation(
            db,
            company_id=workspace.company_id,
            community_id=workspace.community_id,
            command=command,
        )
        assert prepared["action"] == "create" and prepared["owner_enabled"] is None
        assert db.scalar(select(func.count()).select_from(HouseOwner)) == 0
        result = create_house_owner(
            db,
            company_id=workspace.company_id,
            community_id=workspace.community_id,
            actor_id=workspace.account_id,
            command=command,
            house_snapshot=prepared["house_snapshot"],
            request_id="owner-rollback",
        )
        assert result.status == "created"
        assert db.scalar(select(func.count()).select_from(HouseOwner)) == 1
        assert (
            db.scalar(
                select(func.count())
                .select_from(AdminAuditLog)
                .where(AdminAuditLog.request_id == "owner-rollback")
            )
            == 1
        )
        db.rollback()
    with workspace.platform.factory() as db:
        assert db.scalar(select(func.count()).select_from(HouseOwner)) == 0
        assert (
            db.scalar(
                select(func.count())
                .select_from(AdminAuditLog)
                .where(AdminAuditLog.request_id == "owner-rollback")
            )
            == 0
        )


def test_existing_disabled_owner_is_skipped_without_reactivation_or_audit(
    business_workspace: WorkspaceHarness,
) -> None:
    workspace = business_workspace
    house = create_house(
        workspace,
        create_node(workspace)["id"],
        owners=[{"name": "张甲", "phone": "13800000000"}],
    )
    url = housing_path(workspace, f"/houses/{house['id']}/owners")
    owner = workspace.client.get(url).json()["items"][0]
    disabled = workspace.client.patch(
        f"{url}/{owner['id']}", json={"enabled": False}, headers=workspace.headers()
    )
    assert disabled.status_code == 200
    command = HouseOwnerCreationCommand(house["id"], "张甲", "13800000000")
    with workspace.platform.factory() as db:
        prepared = prepare_house_owner_creation(
            db,
            company_id=workspace.company_id,
            community_id=workspace.community_id,
            command=command,
        )
        assert prepared["action"] == "skip"
        assert prepared["target_id"] == owner["id"] and prepared["owner_enabled"] is False
        result = create_house_owner(
            db,
            company_id=workspace.company_id,
            community_id=workspace.community_id,
            actor_id=workspace.account_id,
            command=command,
            house_snapshot=prepared["house_snapshot"],
            expected_target_id=owner["id"],
            allow_existing=True,
            request_id="owner-skip",
        )
        assert result.status == "skipped" and result.owner.id == owner["id"]
        assert result.owner.enabled is False
        db.commit()
    with workspace.platform.factory() as db:
        assert db.scalar(select(func.count()).select_from(HouseOwner)) == 1
        assert (
            db.scalar(
                select(func.count())
                .select_from(AdminAuditLog)
                .where(AdminAuditLog.request_id == "owner-skip")
            )
            == 0
        )


def test_fixed_owner_after_correction_does_not_rebind_to_another_matching_record(
    business_workspace: WorkspaceHarness,
) -> None:
    workspace = business_workspace
    house = create_house(
        workspace,
        create_node(workspace)["id"],
        owners=[{"name": "张甲", "phone": "13800000000"}],
    )
    url = housing_path(workspace, f"/houses/{house['id']}/owners")
    original = workspace.client.get(url).json()["items"][0]
    command = HouseOwnerCreationCommand(house["id"], "张甲", "13800000000")
    with workspace.platform.factory() as db:
        prepared = prepare_house_owner_creation(
            db,
            company_id=workspace.company_id,
            community_id=workspace.community_id,
            command=command,
        )
    changed = workspace.client.patch(
        f"{url}/{original['id']}", json={"name": "张乙"}, headers=workspace.headers()
    )
    assert changed.status_code == 200
    replacement = workspace.client.post(
        url, json={"name": "张甲", "phone": "13800000000"}, headers=workspace.headers()
    )
    assert replacement.status_code == 201
    assert replacement.json()["id"] != original["id"]
    with workspace.platform.factory() as db, pytest.raises(AppError) as caught:
        create_house_owner(
            db,
            company_id=workspace.company_id,
            community_id=workspace.community_id,
            actor_id=workspace.account_id,
            command=command,
            house_snapshot=prepared["house_snapshot"],
            expected_target_id=prepared["target_id"],
            allow_existing=True,
            request_id="owner-fixed",
        )
    assert caught.value.code == "resource.conflict"
    assert caught.value.public_detail == "业主登记资料已变化，请重新核对"
    with workspace.platform.factory() as db:
        assert db.scalar(select(func.count()).select_from(HouseOwner)) == 2


@pytest.mark.parametrize("disabled_resource", ["house", "building"])
def test_skip_still_requires_enabled_house_path(
    business_workspace: WorkspaceHarness, disabled_resource: str
) -> None:
    workspace = business_workspace
    building = create_node(workspace)
    house = create_house(
        workspace,
        building["id"],
        owners=[{"name": "张甲", "phone": "13800000000"}],
    )
    suffix = (
        f"/houses/{house['id']}"
        if disabled_resource == "house"
        else f"/space-nodes/{building['id']}"
    )
    disabled = workspace.client.patch(
        housing_path(workspace, suffix), json={"enabled": False}, headers=workspace.headers()
    )
    assert disabled.status_code == 200
    with workspace.platform.factory() as db, pytest.raises(AppError) as caught:
        prepare_house_owner_creation(
            db,
            company_id=workspace.company_id,
            community_id=workspace.community_id,
            command=HouseOwnerCreationCommand(house["id"], "张甲", "13800000000"),
        )
    assert caught.value.code == "property.housing_disabled"
