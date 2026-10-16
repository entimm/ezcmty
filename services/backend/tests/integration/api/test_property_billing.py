from typing import Any

import pytest
from pytest import MonkeyPatch
from sqlalchemy import func, select
from tests.support.admin import NEW_PASSWORD, TEST_PASSWORD, admin, company
from tests.support.housing import create_house, create_node, housing_path, set_permissions
from tests.support.workspace import PREFIX, WorkspaceHarness, create_community

from backend_app.models.billing import BillOperation, BillSettlementEntry


def test_bill_receipt_correction_void_recreate_and_idempotency(workspace: WorkspaceHarness) -> None:
    workspace.complete_login()
    house = create_house(workspace, create_node(workspace)["id"])
    root = housing_path(workspace, "/bills")
    body = {
        "house_id": house["id"],
        "billing_month": "2024-01",
        "amount_source": "manual",
        "receivable_cents": 10000,
        "manual_amount_reason": "历史补录",
        "external_bill_no": " 001a ",
        "due_date": "2024-02-01",
        "initial_receipt": {"amount_cents": 3000},
    }
    headers = {**workspace.headers(), "Idempotency-Key": "create-bill"}
    created = workspace.client.post(root, json=body, headers=headers)
    assert created.status_code == 201, created.text
    result = created.json()
    bill = result["bill"]
    assert (bill["settled_cents"], bill["outstanding_cents"], bill["row_version"]) == (
        3000,
        7000,
        1,
    )
    assert bill["settlement_status"] == "partially_settled" and bill["is_overdue"]
    assert bill["external_bill_no"] == "001a"
    url = f"{root}/{bill['id']}"

    def post(suffix: str, data: dict[str, Any], key: str) -> Any:
        return workspace.client.post(
            url + suffix, json=data, headers={**workspace.headers(), "Idempotency-Key": key}
        )

    paid = post("/offline-receipts", {"expected_row_version": 1, "amount_cents": 7000}, "receipt")
    assert paid.status_code == 201, paid.text
    assert paid.json()["bill"]["settlement_status"] == "settled"
    # A retry returns the first result even after the bill has advanced.
    assert workspace.client.post(root, json=body, headers=headers).json() == result
    assert workspace.client.get(f"{PREFIX}/bill-operation-results/create-bill").json() == {
        "response_status": 201,
        "result": result,
    }
    changed = {**body, "receivable_cents": 10001}
    assert (
        workspace.client.post(root, json=changed, headers=headers).json()["code"]
        == "billing.idempotency_conflict"
    )
    assert (
        workspace.client.post(
            root, json=body, headers={**headers, "Idempotency-Key": "another"}
        ).json()["code"]
        == "billing.bill_exists"
    )
    assert (
        post("/voids", {"expected_row_version": 2, "reason": "错误"}, "void-paid").json()["code"]
        == "billing.bill_has_settlement"
    )
    assert (
        post("/offline-receipts", {"expected_row_version": 1, "amount_cents": 1}, "stale").json()[
            "code"
        ]
        == "billing.version_conflict"
    )
    first_id = result["settlement_entries"][0]["id"]
    correction = post(
        f"/offline-receipts/{first_id}/corrections",
        {
            "expected_row_version": 2,
            "corrected_amount_cents": 2000,
            "corrected_received_on": "2024-01-15",
            "reason": "金额误录",
        },
        "correction",
    )
    assert correction.status_code == 201, correction.text
    assert [i["amount_cents"] for i in correction.json()["settlement_entries"]] == [-3000, 2000]
    assert correction.json()["bill"]["settled_cents"] == 9000
    assert (
        post(
            f"/offline-receipts/{first_id}/reversals",
            {"expected_row_version": 3, "reason": "重复"},
            "again",
        ).json()["code"]
        == "billing.receipt_already_reversed"
    )
    for version, entry in enumerate(
        [paid.json()["settlement_entries"][0], correction.json()["settlement_entries"][1]], 3
    ):
        reversed_result = post(
            f"/offline-receipts/{entry['id']}/reversals",
            {"expected_row_version": version, "reason": "误登记，非退款"},
            f"reverse-{version}",
        )
        assert reversed_result.status_code == 201, reversed_result.text
    voided = post("/voids", {"expected_row_version": 5, "reason": "重新建账"}, "void")
    assert voided.status_code == 200, voided.text
    assert voided.json()["bill"]["settlement_status"] is None
    assert voided.json()["bill"]["outstanding_cents"] == 0
    assert (
        post(
            "/offline-receipts", {"expected_row_version": 6, "amount_cents": 1}, "after-void"
        ).json()["code"]
        == "billing.bill_voided"
    )
    entries = workspace.client.get(url + "/settlement-entries").json()
    assert entries["total"] == 6 and sum(i["amount_cents"] for i in entries["items"]) == 0
    assert workspace.client.get(url + "/operations", params={"page": 100}).json()["total"] == 6
    body.pop("initial_receipt")
    rebuilt = workspace.client.post(
        root, json=body, headers={**headers, "Idempotency-Key": "rebuild"}
    )
    assert rebuilt.status_code == 201, rebuilt.text
    assert rebuilt.json()["bill"]["id"] != bill["id"]
    assert (
        workspace.client.get(root, params={"outstanding_only": True, "page": 99}).json()["total"]
        == 1
    )
    with workspace.platform.factory() as db:
        assert db.scalar(select(func.count()).select_from(BillOperation)) == 7
        assert db.scalar(select(func.count()).select_from(BillSettlementEntry)) == 6


def test_effective_basis_preview_conflict_and_historical_proof(workspace: WorkspaceHarness) -> None:
    workspace.complete_login()
    house = create_house(workspace, create_node(workspace)["id"])
    base = housing_path(workspace, f"/houses/{house['id']}")
    root = housing_path(workspace, "/bills")

    def basis(version: int, month: str, amount: int) -> dict[str, Any]:
        response = workspace.client.post(
            base + "/property-fee-basis-versions",
            json={
                "expected_latest_version_no": version,
                "effective_from_month": month,
                "house_usage": "residential",
                "fixed_amount_cents": amount,
                "change_reason": "调整",
            },
            headers=workspace.headers(),
        )
        assert response.status_code == 201, response.text
        return dict(response.json())

    first = basis(0, "2024-01", 0)
    basis(1, "2025-01", 20000)
    preview = workspace.client.post(
        base + "/property-fee-calculations",
        json={"billing_month": "2024-03"},
        headers=workspace.headers(),
    ).json()
    assert preview["basis"]["id"] == first["id"] and preview["receivable_cents"] == 0
    body = {
        "house_id": house["id"],
        "billing_month": "2024-03",
        "amount_source": "basis",
        "basis_version_id": first["id"],
        "expected_calculation_rule_version": 1,
        "expected_receivable_cents": 0,
    }
    response = workspace.client.post(
        root, json=body, headers={**workspace.headers(), "Idempotency-Key": "zero"}
    )
    assert response.status_code == 201, response.text
    bill = response.json()["bill"]
    assert bill["settlement_status"] == "settled" and not response.json()["settlement_entries"]
    basis(2, "2024-01", 10000)
    body["billing_month"] = "2024-04"
    conflict = workspace.client.post(
        root, json=body, headers={**workspace.headers(), "Idempotency-Key": "stale-preview"}
    )
    assert conflict.status_code == 409 and conflict.json()["code"] == "billing.basis_changed"
    pinned = workspace.client.get(root + "/" + bill["id"]).json()
    assert pinned["basis"]["id"] == first["id"] and pinned["receivable_cents"] == 0
    set_permissions(workspace, {"property.bill.read"})
    assert workspace.client.get(root + "/" + bill["id"]).status_code == 200
    assert workspace.client.get(base + "/property-fee-basis-versions").status_code == 403
    assert workspace.client.get(f"{PREFIX}/bill-operation-results/zero").status_code == 403


def test_creation_with_initial_payment_is_atomic_and_permission_checked(
    workspace: WorkspaceHarness, monkeypatch: MonkeyPatch
) -> None:
    workspace.complete_login()
    house = create_house(workspace, create_node(workspace)["id"])
    root = housing_path(workspace, "/bills")
    body = {
        "house_id": house["id"],
        "billing_month": "2024-01",
        "amount_source": "manual",
        "receivable_cents": 10000,
        "manual_amount_reason": "历史全额已缴",
        "initial_receipt": {"amount_cents": 10000},
    }
    set_permissions(workspace, {"property.bill.create", "property.bill.read"})
    response = workspace.client.post(
        root, json=body, headers={**workspace.headers(), "Idempotency-Key": "full"}
    )
    assert response.status_code == 403
    set_permissions(
        workspace, {"property.bill.create", "property.bill.read", "property.bill_receipt.create"}
    )

    def fail_audit(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("audit unavailable")

    with monkeypatch.context() as scoped:
        scoped.setattr("backend_app.domain.admin.audit.AdminAudit.record", fail_audit)
        failed = workspace.client.post(
            root, json=body, headers={**workspace.headers(), "Idempotency-Key": "full"}
        )
        assert failed.status_code == 500
    assert workspace.client.get(root).json()["total"] == 0
    with workspace.platform.factory() as db:
        assert db.scalar(select(func.count()).select_from(BillOperation)) == 0
        assert db.scalar(select(func.count()).select_from(BillSettlementEntry)) == 0
    created = workspace.client.post(
        root, json=body, headers={**workspace.headers(), "Idempotency-Key": "full"}
    )
    assert created.status_code == 201, created.text
    assert created.json()["bill"]["settlement_status"] == "settled"
    set_permissions(workspace, {"property.bill.create", "property.bill.read"})
    assert (
        workspace.client.post(
            root, json=body, headers={**workspace.headers(), "Idempotency-Key": "full"}
        ).status_code
        == 403
    )
    assert workspace.client.get(f"{PREFIX}/bill-operation-results/full").status_code == 403


def test_disabled_house_retains_corrections_but_blocks_new_receipts(
    workspace: WorkspaceHarness,
) -> None:
    workspace.complete_login()
    house = create_house(workspace, create_node(workspace)["id"])
    root = housing_path(workspace, "/bills")
    response = workspace.client.post(
        root,
        json={
            "house_id": house["id"],
            "billing_month": "2024-01",
            "amount_source": "manual",
            "receivable_cents": 10000,
            "manual_amount_reason": "历史",
            "initial_receipt": {"amount_cents": 5000},
        },
        headers={**workspace.headers(), "Idempotency-Key": "create"},
    )
    assert response.status_code == 201, response.text
    result = response.json()
    disabled = workspace.client.patch(
        housing_path(workspace, f"/houses/{house['id']}"),
        json={"enabled": False},
        headers=workspace.headers(),
    )
    assert disabled.status_code == 200
    url = f"{root}/{result['bill']['id']}"
    blocked = workspace.client.post(
        url + "/offline-receipts",
        json={"expected_row_version": 1, "amount_cents": 1},
        headers={**workspace.headers(), "Idempotency-Key": "new-receipt"},
    )
    assert blocked.json()["code"] == "property.housing_disabled"
    corrected = workspace.client.post(
        url + f"/offline-receipts/{result['settlement_entries'][0]['id']}/corrections",
        json={
            "expected_row_version": 1,
            "corrected_amount_cents": 10000,
            "corrected_received_on": None,
            "reason": "修正历史金额",
        },
        headers={**workspace.headers(), "Idempotency-Key": "correct"},
    )
    assert corrected.status_code == 201, corrected.text
    assert corrected.json()["bill"]["settlement_status"] == "settled"


def test_bill_input_limits_count_unicode_codepoints(
    workspace: WorkspaceHarness,
) -> None:
    workspace.complete_login()
    house = create_house(workspace, create_node(workspace)["id"])
    root = housing_path(workspace, "/bills")
    body = {
        "house_id": house["id"],
        "billing_month": "2024-01",
        "amount_source": "manual",
        "receivable_cents": 0,
        "manual_amount_reason": "🏠" * 1001,
    }
    headers = {**workspace.headers(), "Idempotency-Key": "length"}
    assert workspace.client.post(root, json=body, headers=headers).status_code == 422
    body["manual_amount_reason"] = "🏠" * 1000
    result = workspace.client.post(root, json=body, headers=headers)
    assert result.status_code == 201, result.text
    assert result.json()["bill"]["manual_amount_reason"] == "🏠" * 1000


@pytest.mark.parametrize("month", ["0000-01", "9999-12", "2024-13"])
def test_invalid_bill_filter_month_returns_validation_error(
    workspace: WorkspaceHarness, month: str
) -> None:
    workspace.complete_login()
    assert (
        workspace.client.get(
            housing_path(workspace, "/bills"), params={"billing_month_from": month}
        ).status_code
        == 422
    )


def test_bill_data_and_recovery_are_hidden_from_other_company(workspace: WorkspaceHarness) -> None:
    w = workspace
    w.complete_login()
    house = create_house(w, create_node(w)["id"])
    root = housing_path(w, "/bills")
    body = {
        "house_id": house["id"],
        "billing_month": "2024-01",
        "amount_source": "manual",
        "receivable_cents": 10000,
        "manual_amount_reason": "历史",
        "initial_receipt": {"amount_cents": 1000},
    }
    created = w.client.post(
        root, json=body, headers={**w.headers(), "Idempotency-Key": "private-bill"}
    )
    assert created.status_code == 201, created.text
    bill_id = created.json()["bill"]["id"]
    other = company(w.platform, "outside")
    outside = create_community(w.platform, other["id"], "outside-community")
    admin(w.platform, other["id"], "outside_admin")
    enabled = w.platform.client.patch(
        f"/v1/property-companies/{other['id']}",
        json={"enabled": True},
        headers=w.platform.headers(),
    )
    assert enabled.status_code == 200, enabled.text
    w.login(name="outside_admin")
    changed = w.client.post(
        f"{PREFIX}/admin-accounts/me/password-changes",
        json={"current_password": TEST_PASSWORD, "new_password": NEW_PASSWORD},
        headers=w.headers(),
    )
    assert changed.status_code == 204, changed.text
    w.login(NEW_PASSWORD, "outside_admin")
    assert w.client.get(root).status_code == 404
    assert w.client.get(f"{root}/{bill_id}").status_code == 404
    assert w.client.get(f"{root}/{bill_id}/settlement-entries").status_code == 404
    assert w.client.get(f"{root}/{bill_id}/operations").status_code == 404
    assert w.client.get(f"{PREFIX}/bill-operation-results/private-bill").status_code == 404
    outside_root = f"{PREFIX}/communities/{outside['id']}/bills"
    assert w.client.get(outside_root).json()["total"] == 0
    assert w.client.get(f"{outside_root}/{bill_id}").status_code == 404
    rejected = w.client.post(
        outside_root, json=body, headers={**w.headers(), "Idempotency-Key": "outside-create"}
    )
    assert rejected.status_code == 404
    assert w.client.get(outside_root).json()["total"] == 0


def test_overdue_filter_and_response_share_one_business_day(
    workspace: WorkspaceHarness, monkeypatch: MonkeyPatch
) -> None:
    from datetime import UTC, datetime

    workspace.complete_login()
    house = create_house(workspace, create_node(workspace)["id"])
    root = housing_path(workspace, "/bills")
    response = workspace.client.post(
        root,
        json={
            "house_id": house["id"],
            "billing_month": "2024-01",
            "amount_source": "manual",
            "receivable_cents": 10000,
            "manual_amount_reason": "历史",
            "due_date": "2026-10-16",
        },
        headers={**workspace.headers(), "Idempotency-Key": "day-boundary"},
    )
    assert response.status_code == 201, response.text
    instants = iter(
        [datetime(2026, 10, 15, 16, tzinfo=UTC), datetime(2026, 10, 16, 16, tzinfo=UTC)]
    )

    class AdvancingClock:
        @staticmethod
        def now(tz: object) -> datetime:
            return next(instants)

    monkeypatch.setattr("backend_app.domain.billing.datetime", AdvancingClock)
    listed = workspace.client.get(root, params={"is_overdue": False})
    assert listed.status_code == 200, listed.text
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["is_overdue"] is False
