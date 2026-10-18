import pytest
from tests.support.payment_api import PaymentHouse


def test_current_authorized_bill_and_entries_are_private_whitelist_projections(
    payment_house: PaymentHouse,
) -> None:
    setup = payment_house
    root = "/v1/miniapp-users/me"
    listing = setup.resident.client.get(
        f"{root}/house-bindings/{setup.binding_id}/bills",
        params={"page_size": 1, "scope": "outstanding"},
        headers=setup.resident.headers(),
    )
    assert listing.status_code == 200, listing.text
    assert listing.headers["Cache-Control"] == "no-store"
    assert listing.json()["total"] == 1
    item = listing.json()["items"][0]
    assert item["billing_month"] == "2024-01"  # History predating the claim remains readable.
    assert item["receivable_cents"] == 10000 and item["outstanding_cents"] == 7000
    assert item["payment_availability"] == "collection_unavailable"
    assert set(item) == {
        "id",
        "property_company_id",
        "property_company_name",
        "community_id",
        "house_id",
        "house_label_snapshot",
        "bill_type",
        "billing_month",
        "period_start",
        "period_end",
        "receivable_cents",
        "settled_cents",
        "outstanding_cents",
        "lifecycle_status",
        "settlement_status",
        "due_date",
        "is_overdue",
        "row_version",
        "payment_availability",
        "own_payment_order_id",
        "created_at",
        "updated_at",
    }
    detail = setup.resident.client.get(
        f"{root}/bills/{setup.bill_id}", headers=setup.resident.headers()
    )
    assert detail.status_code == 200 and detail.json() == item
    entries = setup.resident.client.get(
        f"{root}/bills/{setup.bill_id}/settlement-entries", headers=setup.resident.headers()
    )
    assert entries.status_code == 200 and entries.headers["Cache-Control"] == "no-store"
    entry = entries.json()["items"][0]
    assert entry["display_type"] == "offline_receipt" and entry["own_payment_order_id"] is None
    assert set(entry) == {
        "id",
        "bill_id",
        "entry_type",
        "source_type",
        "amount_cents",
        "received_on",
        "display_type",
        "own_payment_order_id",
        "created_at",
    }
    assert "内部资料" not in listing.text + detail.text + entries.text
    assert "13800138000" not in listing.text + detail.text + entries.text
    assert detail.headers["X-Request-ID"]


@pytest.mark.parametrize("change", ["stranger", "release", "path_disabled"])
def test_bill_list_detail_and_history_require_current_authorization(
    payment_house: PaymentHouse, change: str
) -> None:
    setup = payment_house
    if change == "stranger":
        setup.resident.login("stranger")
    elif change == "release":
        released = setup.resident.client.post(
            f"/v1/miniapp-users/me/house-bindings/{setup.binding_id}/releases",
            json={"expected_row_version": 1},
            headers=setup.resident.headers(),
        )
        assert released.status_code == 200, released.text
    else:
        disabled = setup.workspace.platform.client.patch(
            f"/v1/communities/{setup.workspace.community_id}",
            json={"enabled": False},
            headers=setup.workspace.platform.headers(),
        )
        assert disabled.status_code == 200, disabled.text
    for suffix in (
        f"/house-bindings/{setup.binding_id}/bills",
        f"/bills/{setup.bill_id}",
        f"/bills/{setup.bill_id}/settlement-entries",
    ):
        denied = setup.resident.client.get(
            "/v1/miniapp-users/me" + suffix, headers=setup.resident.headers()
        )
        assert denied.status_code == 404, denied.text
        assert denied.json()["code"] == "resource.not_found"


def test_resident_bill_endpoints_require_resident_identity(payment_house: PaymentHouse) -> None:
    setup = payment_house
    response = setup.resident.client.get(f"/v1/miniapp-users/me/bills/{setup.bill_id}")
    assert response.status_code == 401
