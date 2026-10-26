from typing import Any

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session
from tests.support.admin import Harness
from tests.support.resident import ResidentHarness
from tests.support.workspace import PREFIX, WorkspaceHarness

from backend_app.domain.admin.audit import AdminAudit
from backend_app.models.admin import AdminAuditLog
from backend_app.models.house_claims import HouseClaim, ResidentHouseBinding
from backend_app.models.housing import HouseOwner
from backend_app.models.property import PropertyCompany


@pytest.fixture
def claim_house(business_workspace: WorkspaceHarness) -> dict[str, Any]:
    workspace = business_workspace
    base = f"{PREFIX}/communities/{workspace.community_id}"
    node = workspace.client.post(
        base + "/space-nodes",
        json={"node_type": "building", "name": "悦景一栋"},
        headers=workspace.headers(),
    )
    assert node.status_code == 201, node.text
    house = workspace.client.post(
        base + "/houses",
        json={
            "space_node_id": node.json()["id"],
            "room_no": "101",
            "owners": [{"name": "张三", "phone": "13800138000"}],
        },
        headers=workspace.headers(),
    )
    assert house.status_code == 201, house.text
    return dict(house.json())


def submit(
    resident: ResidentHarness, house: dict[str, Any], *, name: str = "张三", key: str = "claim"
) -> dict[str, Any]:
    phone = resident.phone()
    result = resident.client.post(
        "/v1/miniapp-users/me/house-claims",
        json={"house_id": house["id"], "applicant_name": name, "phone_binding_id": phone["id"]},
        headers=resident.headers(key),
    )
    assert result.status_code == 201, result.text
    return dict(result.json())


def review(
    workspace: WorkspaceHarness,
    claim: dict[str, Any],
    decision: str = "approved",
    reason: str | None = None,
) -> Any:
    return workspace.client.post(
        f"{PREFIX}/house-claims/{claim['id']}/reviews",
        json={"expected_row_version": claim["row_version"], "decision": decision, "reason": reason},
        headers=workspace.headers(),
    )


def test_matched_claim_waits_for_property_and_phone_lifecycle_is_independent(
    business_resident: ResidentHarness,
    business_workspace: WorkspaceHarness,
    claim_house: dict[str, Any],
    business_harness: Harness,
) -> None:
    resident = business_resident
    workspace = business_workspace
    harness = business_harness
    claim = submit(resident, claim_house)
    assert claim["status"] == "pending" and claim["applicant_phone"] == "13800138000"
    assert "match_status" not in claim and "phone_binding_id" not in claim
    phone = resident.client.get(
        "/v1/miniapp-users/me/phone-bindings", headers=resident.headers()
    ).json()["items"][0]
    assert (
        resident.client.delete(
            f"/v1/miniapp-users/me/phone-bindings/{phone['id']}",
            params={"expected_row_version": phone["row_version"]},
            headers=resident.headers(),
        ).status_code
        == 204
    )
    result = review(workspace, claim)
    assert result.status_code == 200, result.text
    assert result.json()["match_status"] == "matched"
    bindings = resident.client.get(
        "/v1/miniapp-users/me/house-bindings", headers=resident.headers()
    ).json()
    assert bindings["total"] == 1 and bindings["items"][0]["effective_enabled"]
    assert (
        resident.client.post(
            f"/v1/miniapp-users/me/house-claims/{claim['id']}/cancellations",
            json={"expected_row_version": 1},
            headers=resident.headers(),
        ).status_code
        == 409
    )
    assert review(workspace, claim).status_code == 409
    with harness.factory() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(AdminAuditLog)
                .where(AdminAuditLog.action == "property.house_claim.review")
            )
            == 1
        )


def test_unmatched_approval_requires_reason_and_never_updates_owner_archive(
    business_resident: ResidentHarness,
    business_workspace: WorkspaceHarness,
    claim_house: dict[str, Any],
    business_harness: Harness,
) -> None:
    resident = business_resident
    workspace = business_workspace
    harness = business_harness
    claim = submit(resident, claim_house, name="李四")
    assert review(workspace, claim).status_code == 422
    result = review(workspace, claim, reason="已当面核实产权证明，资料后续维护")
    assert result.status_code == 200, result.text
    assert result.json()["match_status"] == "unmatched"
    with harness.factory() as db:
        owners = db.scalars(select(HouseOwner)).all()
        assert len(owners) == 1 and owners[0].name == "张三"
        audits = db.scalars(
            select(AdminAuditLog).where(AdminAuditLog.action == "property.house_claim.review")
        ).all()
        assert len(audits) == 1
        assert audits[0].safe_metadata == {
            "status": "approved",
            "match_status": "unmatched",
            "house_id": claim_house["id"],
        }


def test_cancel_then_reapply_release_and_reapply_preserve_history(
    business_resident: ResidentHarness,
    business_workspace: WorkspaceHarness,
    claim_house: dict[str, Any],
) -> None:
    resident = business_resident
    workspace = business_workspace
    first = submit(resident, claim_house)
    cancelled = resident.client.post(
        f"/v1/miniapp-users/me/house-claims/{first['id']}/cancellations",
        json={"expected_row_version": 1},
        headers=resident.headers(),
    )
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    assert review(workspace, first).status_code == 409
    second = submit(resident, claim_house, key="second")
    assert review(workspace, second).status_code == 200
    binding = resident.client.get(
        "/v1/miniapp-users/me/house-bindings", headers=resident.headers()
    ).json()["items"][0]
    released = resident.client.post(
        f"/v1/miniapp-users/me/house-bindings/{binding['id']}/releases",
        json={"expected_row_version": 1},
        headers=resident.headers(),
    )
    assert released.status_code == 200 and released.json()["status"] == "released"
    third = submit(resident, claim_house, key="third")
    assert review(workspace, third).status_code == 200
    history = resident.client.get(
        "/v1/miniapp-users/me/house-bindings", headers=resident.headers()
    ).json()
    assert history["total"] == 2
    assert {item["status"] for item in history["items"]} == {"active", "released"}


@pytest.mark.parametrize("failure", ["binding", "audit"])
def test_approval_failure_rolls_back_application_binding_and_audit(
    business_resident: ResidentHarness,
    business_workspace: WorkspaceHarness,
    claim_house: dict[str, Any],
    business_harness: Harness,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    resident = business_resident
    workspace = business_workspace
    harness = business_harness
    claim = submit(resident, claim_house)

    def fail_audit(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("injected audit failure")

    def fail_binding(db: Session, *args: Any) -> None:
        if any(isinstance(item, ResidentHouseBinding) for item in db.new):
            raise RuntimeError("injected binding failure")

    with monkeypatch.context() as patch:
        if failure == "audit":
            patch.setattr(AdminAudit, "record", fail_audit)
        else:
            event.listen(Session, "before_flush", fail_binding)
        try:
            result = review(workspace, claim)
            assert result.status_code == 500, result.text
        finally:
            if failure == "binding":
                event.remove(Session, "before_flush", fail_binding)
    with harness.factory() as db:
        item = db.get(HouseClaim, claim["id"])
        assert (
            item and item.status == "pending" and item.row_version == 1 and item.reviewed_at is None
        )
        assert db.scalar(select(func.count()).select_from(ResidentHouseBinding)) == 0
        assert (
            db.scalar(
                select(func.count())
                .select_from(AdminAuditLog)
                .where(AdminAuditLog.action == "property.house_claim.review")
            )
            == 0
        )
    assert review(workspace, claim).status_code == 200


def test_claim_scope_and_duplicate_pending_are_enforced(
    business_resident: ResidentHarness,
    business_workspace: WorkspaceHarness,
    claim_house: dict[str, Any],
) -> None:
    resident = business_resident
    workspace = business_workspace
    claim = submit(resident, claim_house)
    phone = resident.phone()
    data = {
        "house_id": claim_house["id"],
        "applicant_name": "张三",
        "phone_binding_id": phone["id"],
    }
    replay = resident.client.post(
        "/v1/miniapp-users/me/house-claims", json=data, headers=resident.headers("claim")
    )
    assert replay.status_code == 200 and replay.json()["id"] == claim["id"]
    assert (
        resident.client.post(
            "/v1/miniapp-users/me/house-claims", json=data, headers=resident.headers("duplicate")
        ).status_code
        == 409
    )
    resident.login("second-user")
    assert (
        resident.client.get(
            f"/v1/miniapp-users/me/house-claims/{claim['id']}", headers=resident.headers()
        ).status_code
        == 404
    )
    assert (
        resident.client.get("/v1/miniapp-users/me/house-claims", headers=resident.headers()).json()[
            "total"
        ]
        == 0
    )
    # One house can have independently authorized users.
    second = submit(resident, claim_house, key="second-user")
    assert review(workspace, claim).status_code == 200
    assert review(workspace, second).status_code == 200


def test_claimable_options_follow_enabled_path_and_never_expose_owners(
    business_resident: ResidentHarness,
    business_workspace: WorkspaceHarness,
    claim_house: dict[str, Any],
) -> None:
    resident = business_resident
    workspace = business_workspace
    prefix = f"/v1/claimable-communities/{workspace.community_id}"
    nodes = resident.client.get(prefix + "/space-nodes", headers=resident.headers()).json()
    assert nodes["total"] == 1 and nodes["items"][0]["node_type"] == "building"
    options = resident.client.get(
        prefix + "/houses",
        params={"space_node_id": claim_house["space_node_id"]},
        headers=resident.headers(),
    )
    assert options.status_code == 200, options.text
    assert options.json()["total"] == 1
    assert set(options.json()["items"][0]) == {
        "id",
        "community_id",
        "space_node_id",
        "room_no",
        "display_address",
    }
    disabled = workspace.client.patch(
        f"{PREFIX}/communities/{workspace.community_id}/space-nodes/{claim_house['space_node_id']}",
        json={"enabled": False},
        headers=workspace.headers(),
    )
    assert disabled.status_code == 200
    assert (
        resident.client.get(prefix + "/space-nodes", headers=resident.headers()).json()["total"]
        == 0
    )
    assert (
        resident.client.get(
            prefix + f"/houses/{claim_house['id']}", headers=resident.headers()
        ).status_code
        == 404
    )


def test_stopped_company_does_not_block_resident_history_or_release(
    business_resident: ResidentHarness,
    business_workspace: WorkspaceHarness,
    claim_house: dict[str, Any],
    business_harness: Harness,
) -> None:
    resident = business_resident
    workspace = business_workspace
    harness = business_harness
    claim = submit(resident, claim_house)
    assert review(workspace, claim).status_code == 200
    with harness.factory() as db:
        company = db.get(PropertyCompany, workspace.company_id)
        assert company
        company.enabled = False
        db.commit()
    binding = resident.client.get(
        "/v1/miniapp-users/me/house-bindings", headers=resident.headers()
    ).json()["items"][0]
    assert not binding["effective_enabled"]
    assert (
        resident.client.get(
            f"/v1/miniapp-users/me/house-claims/{claim['id']}", headers=resident.headers()
        ).status_code
        == 200
    )
    assert (
        resident.client.post(
            f"/v1/miniapp-users/me/house-bindings/{binding['id']}/releases",
            json={"expected_row_version": 1},
            headers=resident.headers(),
        ).status_code
        == 200
    )


def test_revoke_requires_reason_and_current_version(
    business_resident: ResidentHarness,
    business_workspace: WorkspaceHarness,
    claim_house: dict[str, Any],
) -> None:
    resident = business_resident
    workspace = business_workspace
    claim = submit(resident, claim_house)
    assert review(workspace, claim).status_code == 200
    binding = workspace.client.get(
        f"{PREFIX}/resident-house-bindings", headers=workspace.headers()
    ).json()["items"][0]
    url = f"{PREFIX}/resident-house-bindings/{binding['id']}/revocations"
    assert (
        workspace.client.post(
            url, json={"expected_row_version": 1, "reason": " "}, headers=workspace.headers()
        ).status_code
        == 422
    )
    result = workspace.client.post(
        url, json={"expected_row_version": 1, "reason": "产权已变更"}, headers=workspace.headers()
    )
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "revoked" and not result.json()["effective_enabled"]
    assert (
        workspace.client.post(
            url, json={"expected_row_version": 1, "reason": "重复撤销"}, headers=workspace.headers()
        ).status_code
        == 409
    )


def test_property_data_and_counts_cannot_cross_companies(
    business_resident: ResidentHarness,
    business_workspace: WorkspaceHarness,
    claim_house: dict[str, Any],
    business_harness: Harness,
) -> None:
    resident = business_resident
    workspace = business_workspace
    harness = business_harness
    from tests.support.admin import admin, company

    claim = submit(resident, claim_house)
    other = company(harness, "other-company")
    admin(harness, other["id"], "other-admin")
    harness.client.patch(
        f"/v1/property-companies/{other['id']}", json={"enabled": True}, headers=harness.headers()
    )
    workspace.login(name="other-admin")
    from tests.support.admin import NEW_PASSWORD, TEST_PASSWORD

    workspace.client.post(
        f"{PREFIX}/admin-accounts/me/password-changes",
        json={"current_password": TEST_PASSWORD, "new_password": NEW_PASSWORD},
        headers=workspace.headers(),
    )
    workspace.login(name="other-admin", password=NEW_PASSWORD)
    assert (
        workspace.client.get(
            f"{PREFIX}/house-claims/{claim['id']}", headers=workspace.headers()
        ).status_code
        == 404
    )
    assert (
        workspace.client.get(f"{PREFIX}/house-claims", headers=workspace.headers()).json()["total"]
        == 0
    )
    assert review(workspace, claim).status_code == 404
