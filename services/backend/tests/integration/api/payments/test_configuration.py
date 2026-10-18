import pytest
from tests.support.admin import NEW_PASSWORD, TEST_PASSWORD, Harness, company
from tests.support.housing import set_permissions
from tests.support.workspace import PREFIX, WorkspaceHarness

PLATFORM_PERMISSIONS = {
    "platform.payment_config.read",
    "platform.payment_config.manage",
    "platform.payment.read",
    "platform.payment_funds.read",
    "platform.payment_funds.recover",
    "platform.payment_reconciliation.read",
    "platform.payment_reconciliation.recheck",
}
PROPERTY_PERMISSIONS = {
    "property.payment_config.read",
    "property.payment.read",
    "property.payment_funds.read",
    "property.payment_reconciliation.read",
}


def test_platform_assignable_payment_permissions_project_into_full_session(
    harness: Harness,
) -> None:
    harness.login()
    catalog = harness.client.get("/v1/admin-permissions")
    assert catalog.status_code == 200
    advertised = {item["code"] for item in catalog.json() if item["assignable"]}
    assert PLATFORM_PERMISSIONS <= advertised
    target = company(harness)
    role = harness.client.post(
        "/v1/admin-roles",
        json={"code": "payment_reader", "name": "支付配置只读"},
        headers=harness.headers(),
    )
    assert role.status_code == 201, role.text
    assigned = harness.client.put(
        f"/v1/admin-roles/{role.json()['id']}/permissions",
        json={"permissions": ["platform.payment_config.read"]},
        headers=harness.headers(),
    )
    assert assigned.status_code == 200, assigned.text
    account = harness.client.post(
        "/v1/admin-accounts",
        json={
            "login_name": "payment_reader",
            "display_name": "支付配置只读",
            "password": TEST_PASSWORD,
            "role_ids": [role.json()["id"]],
        },
        headers=harness.headers(),
    )
    assert account.status_code == 201, account.text
    restricted = harness.login("payment_reader", TEST_PASSWORD)
    assert restricted["must_change_password"] and restricted["permissions"] == []
    root = f"/v1/property-companies/{target['id']}"
    assert harness.client.get(root + "/payment-configuration").status_code == 403
    changed = harness.client.post(
        "/v1/admin-accounts/me/password-changes",
        json={"current_password": TEST_PASSWORD, "new_password": NEW_PASSWORD},
        headers=harness.headers(),
    )
    assert changed.status_code == 204, changed.text
    logged_in = harness.login("payment_reader")
    current = harness.client.get("/v1/admin-sessions/current")
    assert (
        logged_in["permissions"]
        == current.json()["permissions"]
        == ["platform.payment_config.read"]
    )
    read = harness.client.get(root + "/payment-configuration")
    assert read.status_code == 200 and read.headers["Cache-Control"] == "no-store"
    assert read.json()["configuration_token"]
    refused = harness.client.post(
        root + "/merchant-bindings",
        json={
            "merchant_no": "merchant_test",
            "merchant_name": "测试物业",
            "expected_configuration_token": read.json()["configuration_token"],
        },
        headers={**harness.headers(), "Idempotency-Key": "unauthorized-binding"},
    )
    assert refused.status_code == 403
    assert refused.json()["code"] == "auth.forbidden"


def test_binding_creation_requires_csrf_and_keeps_durable_replay_and_no_store(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APP_WECHATPAY_SERVICE_PROVIDER_MERCHANT_NO", "sp_test_only")
    from backend_app.core.config import get_settings

    get_settings.cache_clear()
    harness.login()
    target = company(harness)
    root = f"/v1/property-companies/{target['id']}"
    config = harness.client.get(root + "/payment-configuration")
    body = {
        "merchant_no": "merchant_test_only",
        "merchant_name": "隔离测试物业",
        "expected_configuration_token": config.json()["configuration_token"],
    }
    denied = harness.client.post(
        root + "/merchant-bindings", json=body, headers={"Idempotency-Key": "binding"}
    )
    assert denied.status_code == 403
    headers = {**harness.headers(), "Idempotency-Key": "binding"}
    created = harness.client.post(root + "/merchant-bindings", json=body, headers=headers)
    assert created.status_code == 201, created.text
    assert created.headers["Cache-Control"] == "no-store"
    assert created.json()["enabled"] is False
    replay = harness.client.post(root + "/merchant-bindings", json=body, headers=headers)
    assert replay.status_code == 201 and replay.json() == created.json()
    conflict = harness.client.post(
        root + "/merchant-bindings",
        json={**body, "merchant_name": "另一商户"},
        headers=headers,
    )
    assert conflict.status_code == 409 and conflict.json()["code"] == "payment.idempotency_conflict"
    history = harness.client.get(root + "/merchant-bindings")
    assert history.status_code == 200 and history.json()["total"] == 1
    assert history.headers["Cache-Control"] == "no-store"
    assert set(created.json()) == {
        "id",
        "property_company_id",
        "service_provider_merchant_no",
        "merchant_no",
        "merchant_name",
        "enabled",
        "max_ratio_bps",
        "ratio_checked_at",
        "row_version",
        "created_at",
        "updated_at",
    }


def test_property_session_exposes_only_read_payment_permissions_and_config_routes(
    workspace: WorkspaceHarness,
) -> None:
    workspace.complete_login()
    current = workspace.client.get(f"{PREFIX}/admin-sessions/current")
    permissions = set(current.json()["permissions"])
    assert PROPERTY_PERMISSIONS <= permissions
    assert not any(code.startswith("platform.payment") for code in permissions)
    response = workspace.client.get(f"{PREFIX}/payment-configuration")
    assert response.status_code == 200, response.text
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json()["property_company_id"] == workspace.company_id
    for path in ("/merchant-bindings", "/profit-sharing-rule-versions"):
        read = workspace.client.get(PREFIX + path)
        assert read.status_code == 200 and read.headers["Cache-Control"] == "no-store"
        denied = workspace.client.post(PREFIX + path, json={}, headers=workspace.headers())
        assert denied.status_code == 405
    assert (
        workspace.client.put(
            f"{PREFIX}/active-merchant-binding", json={}, headers=workspace.headers()
        ).status_code
        == 404
    )
    assert (
        workspace.client.get(
            f"{PREFIX}/property-companies/{workspace.company_id}/payment-configuration"
        ).status_code
        == 404
    )
    set_permissions(workspace, {"property.community.read"})
    refused = workspace.client.get(f"{PREFIX}/payment-configuration")
    assert refused.status_code == 403 and refused.json()["code"] == "auth.forbidden"


@pytest.mark.parametrize(
    "resource", ["payment-configuration", "merchant-bindings", "profit-sharing-rule-versions"]
)
def test_platform_configuration_requires_login(harness: Harness, resource: str) -> None:
    harness.login()
    target = company(harness)
    harness.client.delete("/v1/admin-sessions/current", headers=harness.headers())
    assert (
        harness.client.get(f"/v1/property-companies/{target['id']}/{resource}").status_code == 401
    )
