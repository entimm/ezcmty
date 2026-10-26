import pytest
from tests.support.housing import create_house, create_node, housing_path
from tests.support.payment_api import PaymentHouse
from tests.support.resident import ResidentHarness
from tests.support.workspace import PREFIX, WorkspaceHarness


@pytest.fixture
def payment_house(
    business_workspace: WorkspaceHarness, business_resident: ResidentHarness
) -> PaymentHouse:
    workspace, resident = business_workspace, business_resident
    house = create_house(
        workspace,
        create_node(workspace)["id"],
        owners=[{"name": "张三", "phone": "13800138000"}],
    )
    phone = resident.phone()
    claim = resident.client.post(
        "/v1/miniapp-users/me/house-claims",
        json={
            "house_id": house["id"],
            "applicant_name": "张三",
            "phone_binding_id": phone["id"],
        },
        headers=resident.headers("claim-payment-house"),
    )
    assert claim.status_code == 201, claim.text
    approved = workspace.client.post(
        f"{PREFIX}/house-claims/{claim.json()['id']}/reviews",
        json={"expected_row_version": 1, "decision": "approved"},
        headers=workspace.headers(),
    )
    assert approved.status_code == 200, approved.text
    bindings = resident.client.get(
        "/v1/miniapp-users/me/house-bindings", headers=resident.headers()
    )
    assert bindings.status_code == 200
    binding_id = bindings.json()["items"][0]["id"]
    bill = workspace.client.post(
        housing_path(workspace, "/bills"),
        json={
            "house_id": house["id"],
            "billing_month": "2024-01",
            "amount_source": "manual",
            "receivable_cents": 10000,
            "manual_amount_reason": "内部资料：不得向居民公开",
            "initial_receipt": {"amount_cents": 3000, "reason": "内部收款凭据"},
        },
        headers={**workspace.headers(), "Idempotency-Key": "payment-bill"},
    )
    assert bill.status_code == 201, bill.text
    return PaymentHouse(workspace, resident, house["id"], binding_id, bill.json()["bill"]["id"])
