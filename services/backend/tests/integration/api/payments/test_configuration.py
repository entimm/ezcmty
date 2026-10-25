import json

import pytest
from sqlalchemy import func, select
from tests.support.admin import NEW_PASSWORD, TEST_PASSWORD, Harness, company
from tests.support.housing import set_permissions
from tests.support.wechatpay import WechatPayHarness
from tests.support.workspace import PREFIX, WorkspaceHarness

from backend_app.core.config import get_settings
from backend_app.models.admin import AdminAuditLog, utc_now
from backend_app.models.payments import PaymentChannelRequest, PropertyMerchantBinding

PLATFORM_PERMISSIONS = {
    "platform.payment_config.manage",
    "platform.payment_reconciliation.manage",
    "platform.payment.read",
    "platform.payment_config.read",
    "platform.payment_reconciliation.read",
    "platform.payment.recover",
}
PROPERTY_PERMISSIONS = {"property.payment.read"}


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


@pytest.mark.parametrize("operation", ["activate", "publish_rule"])
@pytest.mark.parametrize("invalid_setting", ["private_key", "verification_keys"])
def test_invalid_channel_credentials_reject_configuration_writes_without_changes(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, operation: str, invalid_setting: str
) -> None:
    peer = WechatPayHarness()
    keys = dict(peer.config.verification_keys)
    if invalid_setting == "verification_keys":
        keys["WX_MERCHANT_SERIAL_NO"] = peer.config.merchant_certificate_serial
    values = {
        "APP_WECHAT_MINIAPP_APP_ID": peer.config.app_id,
        "APP_WECHATPAY_SERVICE_PROVIDER_MERCHANT_NO": peer.config.service_provider_merchant_no,
        "APP_WECHATPAY_MERCHANT_CERTIFICATE_SERIAL": peer.config.merchant_certificate_serial,
        "APP_WECHATPAY_MERCHANT_PRIVATE_KEY": (
            "invalid isolated private key"
            if invalid_setting == "private_key"
            else peer.config.merchant_private_key.get_secret_value()
        ),
        "APP_WECHATPAY_API_V3_KEY": peer.config.api_v3_key.get_secret_value(),
        "APP_WECHATPAY_VERIFICATION_KEYS": json.dumps(keys),
        "APP_WECHATPAY_ENCRYPTION_KEY_ID": peer.config.encryption_key_id,
        "APP_WECHATPAY_PAYMENT_NOTIFY_URL": peer.config.payment_notify_url,
        "APP_WECHATPAY_PLATFORM_RECEIVER_NAME": "隔离测试平台",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()

    def unexpected_channel_request(*args: object, **kwargs: object) -> None:
        raise AssertionError("Invalid configuration must not send channel requests")

    monkeypatch.setattr(
        "backend_app.integrations.wechatpay.client.WechatPayClient._send",
        unexpected_channel_request,
    )
    harness.login()
    target = company(harness)
    root = f"/v1/property-companies/{target['id']}"
    token = harness.client.get(root + "/payment-configuration").json()["configuration_token"]
    created = harness.client.post(
        root + "/merchant-bindings",
        json={
            "merchant_no": "1900000002",
            "merchant_name": "隔离测试物业",
            "expected_configuration_token": token,
        },
        headers={**harness.headers(), "Idempotency-Key": "binding"},
    )
    assert created.status_code == 201, created.text
    if operation == "publish_rule":
        with harness.factory() as db:
            binding = db.get(PropertyMerchantBinding, created.json()["id"])
            assert binding
            binding.enabled = True
            binding.row_version += 1
            binding.max_ratio_bps = 3000
            binding.ratio_checked_at = utc_now()
            db.commit()
    before = harness.client.get(root + "/payment-configuration").json()
    token = before["configuration_token"]
    if operation == "activate":
        response = harness.client.put(
            root + "/active-merchant-binding",
            json={
                "binding_id": created.json()["id"],
                "expected_configuration_token": token,
            },
            headers=harness.headers(),
        )
    else:
        response = harness.client.post(
            root + "/profit-sharing-rule-versions",
            json={"items": [{"rate_bps": 300}], "expected_configuration_token": token},
            headers={**harness.headers(), "Idempotency-Key": "rule"},
        )
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "payment.configuration_unavailable"
    assert "invalid isolated private key" not in response.text
    assert harness.client.get(root + "/payment-configuration").json() == before
    assert harness.client.get(root + "/profit-sharing-rule-versions").json()["total"] == 0
    with harness.factory() as db:
        assert db.scalar(select(func.count()).select_from(PaymentChannelRequest)) == 0
        assert (
            db.scalar(
                select(func.count())
                .select_from(AdminAuditLog)
                .where(
                    AdminAuditLog.action.in_(
                        ["payment.merchant_binding.activate", "payment.profit_sharing_rule.create"]
                    )
                )
            )
            == 0
        )


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
    set_permissions(workspace, {"platform.onboarding.read"})
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
