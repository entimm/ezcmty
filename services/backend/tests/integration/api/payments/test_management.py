import pytest
from sqlalchemy import select
from tests.support.admin import admin, company
from tests.support.housing import set_permissions
from tests.support.payment_api import PaymentHouse
from tests.support.payment_management import managed_scenario
from tests.support.workspace import PREFIX

from backend_app.models.payments import ProfitSharingOrder


def test_managed_payment_and_sharing_are_exact_safe_projections(
    payment_house: PaymentHouse,
) -> None:
    house = payment_house
    scenario = managed_scenario(house)
    platform = house.workspace.platform.client
    for client, prefix in ((platform, "/v1"), (house.workspace.client, PREFIX)):
        listing = client.get(prefix + "/payment-orders", params={"page_size": 1})
        assert listing.status_code == 200, listing.text
        assert listing.headers["Cache-Control"] == "no-store"
        assert listing.json()["total"] == 1
        item = listing.json()["items"][0]
        assert item["id"] == scenario.payment.order_id
        assert item["amount_cents"] == 7000
        assert item["status"] == "succeeded" and item["confirmation_status"] == "posted"
        assert item["payer_total_cents"] is None
        assert item["items"][0]["bill_id"] == house.bill_id
        assert "payer_user_id" not in item and "prepay_token" not in item
        detail = client.get(prefix + f"/payment-orders/{scenario.payment.order_id}")
        assert detail.status_code == 200 and detail.json() == item
        empty = client.get(prefix + "/payment-orders", params={"page": 2, "page_size": 1})
        assert empty.status_code == 200 and empty.json()["total"] == 1
        assert empty.json()["items"] == []
        shares = client.get(prefix + "/profit-sharing-orders")
        assert shares.status_code == 200 and shares.json()["total"] == 1
        share = shares.json()["items"][0]
        assert share["status"] == "pending"
        assert share["items"][0]["allocation_cents"] == 210
        assert share["items"][0]["amount_cents"] == 210
        assert share["items"][0]["result"] is None
        assert client.get(prefix + f"/profit-sharing-orders/{share['id']}").json() == share
        assert "13800138000" not in listing.text + shares.text


def test_unknown_unfreeze_amount_is_not_inferred(payment_house: PaymentHouse) -> None:
    house = payment_house
    scenario = managed_scenario(house, rate_bps=0)
    for client, prefix in (
        (house.workspace.platform.client, "/v1"),
        (house.workspace.client, PREFIX),
    ):
        response = client.get(
            prefix + "/payment-unfreeze-orders",
            params={"payment_order_id": scenario.payment.order_id},
        )
        assert response.status_code == 200, response.text
        assert response.json()["total"] == 1
        item = response.json()["items"][0]
        assert item["status"] == "pending" and item["unfrozen_cents"] is None
        assert client.get(prefix + f"/payment-unfreeze-orders/{item['id']}").json() == item


def test_property_reconciliation_filters_before_count_and_projects_company_summary(
    payment_house: PaymentHouse,
) -> None:
    house = payment_house
    scenario = managed_scenario(house)
    platform = house.workspace.platform.client
    complete = platform.get(f"/v1/payment-reconciliation-runs/{scenario.run_id}")
    assert complete.status_code == 200, complete.text
    assert complete.json()["projection"] == "batch"
    assert complete.json()["summary"]["local_count"] == 99
    assert complete.json()["source_digest"] == "SHA256:isolated_hash"
    client = house.workspace.client
    runs = client.get(PREFIX + "/payment-reconciliation-runs", params={"page_size": 1})
    assert runs.status_code == 200 and runs.json()["total"] == 1
    item = runs.json()["items"][0]
    assert item["projection"] == "company"
    assert item["property_company_id"] == house.workspace.company_id
    assert item["summary"]["local_count"] == 1
    assert item["summary"]["local_amount_cents"] == 7000
    assert item["summary"]["channel_fee_cents"] is None and item["source_digest"] is None
    assert "private_summary" not in runs.text and "990000" not in runs.text
    assert (
        client.get(PREFIX + f"/payment-reconciliation-runs/{scenario.platform_run_id}").status_code
        == 404
    )
    differences = client.get(PREFIX + "/payment-reconciliation-discrepancies")
    assert differences.status_code == 200 and differences.json()["total"] == 1
    difference = differences.json()["items"][0]
    assert difference["id"] == scenario.linked_difference_id
    assert difference["evidence"]["source_digest"] == "SHA256:isolated_digest"
    assert "private_raw_statement" not in differences.text
    assert "sensitive-openid" not in differences.text and "13800138000" not in differences.text
    assert (
        client.get(
            PREFIX + f"/payment-reconciliation-discrepancies/{scenario.unlinked_difference_id}"
        ).status_code
        == 404
    )
    empty = client.get(
        PREFIX + "/payment-reconciliation-discrepancies", params={"page": 2, "page_size": 1}
    )
    assert empty.json()["items"] == [] and empty.json()["total"] == 1
    override = client.get(
        PREFIX + "/payment-orders", params={"property_company_id": house.workspace.company_id}
    )
    assert override.status_code == 422
    for resource in ("payment-reconciliation-runs", "payment-reconciliation-discrepancies"):
        forbidden_statement = client.get(
            PREFIX + "/" + resource, params={"statement_type": "platform_fundflow"}
        )
        assert forbidden_statement.status_code == 404
        assert forbidden_statement.json()["code"] == "resource.not_found"


def test_cross_company_records_and_counts_are_invisible(payment_house: PaymentHouse) -> None:
    house = payment_house
    scenario = managed_scenario(house)
    harness = house.workspace.platform
    other = company(harness, "other-payment-company")
    admin(harness, other["id"], "other_property")
    enabled = harness.client.patch(
        f"/v1/property-companies/{other['id']}", json={"enabled": True}, headers=harness.headers()
    )
    assert enabled.status_code == 200
    house.workspace.login(name="other_property")
    from tests.support.admin import NEW_PASSWORD, TEST_PASSWORD

    changed = house.workspace.client.post(
        PREFIX + "/admin-accounts/me/password-changes",
        json={"current_password": TEST_PASSWORD, "new_password": NEW_PASSWORD},
        headers=house.workspace.headers(),
    )
    assert changed.status_code == 204
    house.workspace.login(NEW_PASSWORD, "other_property")
    with harness.factory() as db:
        share = db.scalars(select(ProfitSharingOrder)).one()
        share_id = share.id
    for resource, identifier in (
        ("payment-orders", scenario.payment.order_id),
        ("profit-sharing-orders", share_id),
        ("payment-reconciliation-runs", scenario.run_id),
        ("payment-reconciliation-discrepancies", scenario.linked_difference_id),
    ):
        listing = house.workspace.client.get(PREFIX + "/" + resource)
        assert listing.status_code == 200, listing.text
        assert listing.json()["items"] == [] and listing.json()["total"] == 0
        assert house.workspace.client.get(PREFIX + f"/{resource}/{identifier}").status_code == 404


@pytest.mark.parametrize(
    ("permission", "allowed", "forbidden"),
    [
        ("property.payment.read", "payment-orders", "profit-sharing-orders"),
        ("property.payment_funds.read", "profit-sharing-orders", "payment-orders"),
        ("property.payment_reconciliation.read", "payment-reconciliation-runs", "payment-orders"),
    ],
)
def test_payment_read_permissions_are_independent(
    payment_house: PaymentHouse, permission: str, allowed: str, forbidden: str
) -> None:
    house = payment_house
    managed_scenario(house)
    set_permissions(house.workspace, {permission})
    assert house.workspace.client.get(PREFIX + "/" + allowed).status_code == 200
    denied = house.workspace.client.get(PREFIX + "/" + forbidden)
    assert denied.status_code == 403 and denied.json()["code"] == "auth.forbidden"
