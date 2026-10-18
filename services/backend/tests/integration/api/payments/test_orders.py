from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy import func, select
from tests.support.payment_api import PaymentHouse
from tests.support.wechatpay import WechatPayHarness

from backend_app.core.config import get_settings
from backend_app.models.admin import utc_now
from backend_app.models.payments import (
    PaymentChannelRequest,
    PaymentOrder,
    PaymentTask,
    ProfitSharingRuleVersion,
    ProfitSharingRuleVersionItem,
    PropertyMerchantBinding,
)

ROOT = "/v1/miniapp-users/me/payment-orders"


def configure(setup: PaymentHouse, monkeypatch: pytest.MonkeyPatch) -> WechatPayHarness:
    peer = WechatPayHarness()
    settings = get_settings().model_copy(
        update={
            "payment_new_orders_enabled": True,
            "wechat_miniapp_app_id": peer.config.app_id,
            "wechatpay_service_provider_merchant_no": peer.config.service_provider_merchant_no,
            "wechatpay_merchant_certificate_serial": peer.config.merchant_certificate_serial,
            "wechatpay_merchant_private_key": peer.config.merchant_private_key,
            "wechatpay_api_v3_key": peer.config.api_v3_key,
            "wechatpay_verification_keys": peer.config.verification_keys,
            "wechatpay_encryption_key_id": peer.config.encryption_key_id,
            "wechatpay_payment_notify_url": peer.config.payment_notify_url,
            "wechatpay_platform_receiver_name": SecretStr("隔离平台"),
        }
    )
    monkeypatch.setattr("backend_app.api.resident.payments.get_settings", lambda: settings)
    with setup.workspace.platform.factory() as db:
        binding = PropertyMerchantBinding(
            property_company_id=setup.workspace.company_id,
            service_provider_merchant_no="1900000001",
            merchant_no="1900000002",
            merchant_name="隔离物业",
            enabled=False,
            max_ratio_bps=3000,
            ratio_checked_at=utc_now(),
            created_by=setup.workspace.account_id,
            idempotency_key="binding",
            request_fingerprint="1" * 64,
        )
        rule = ProfitSharingRuleVersion(
            property_company_id=setup.workspace.company_id,
            version_no=1,
            created_by=setup.workspace.account_id,
            idempotency_key="rule",
            request_fingerprint="2" * 64,
        )
        db.add_all([binding, rule])
        db.flush()
        binding.enabled = True
        binding.row_version += 1
        binding.updated_at = utc_now()
        db.add(
            ProfitSharingRuleVersionItem(
                rule_version_id=rule.id,
                receiver_account="1900000001",
                receiver_name="隔离平台",
                rate_bps=300,
            )
        )
        db.add(
            PaymentChannelRequest(
                operation="receiver_add",
                merchant_binding_id=binding.id,
                request_snapshot={},
                response_snapshot={"merchant_no": "1900000002", "receiver_account": "1900000001"},
                outcome="verified_response",
                finished_at=utc_now(),
                http_status=200,
                request_id="ready",
            )
        )
        db.commit()
    return peer


def body(setup: PaymentHouse) -> dict[str, Any]:
    bill = setup.resident.client.get(
        f"/v1/miniapp-users/me/bills/{setup.bill_id}", headers=setup.resident.headers()
    )
    assert bill.status_code == 200
    return {
        "items": [{"bill_id": setup.bill_id, "expected_row_version": bill.json()["row_version"]}]
    }


def test_resident_order_http_create_read_recover_and_replay_after_release(
    payment_house: PaymentHouse, monkeypatch: pytest.MonkeyPatch
) -> None:
    setup = payment_house
    configure(setup, monkeypatch)
    client = setup.resident.client
    data = body(setup)
    response = client.post(ROOT, json=data, headers=setup.resident.headers("order"))
    assert response.status_code == 201, response.text
    result = response.json()
    assert result["amount_cents"] == 7000 and result["confirmation_status"] == "unconfirmed"
    assert result["status"] == "pending" and result["created_at"].endswith("Z")
    assert response.headers["Cache-Control"] == "no-store"
    order_id = result["id"]
    for payload in (
        result,
        client.get(ROOT + f"/{order_id}", headers=setup.resident.headers()).json(),
    ):
        assert "prepay_token" not in payload and "channel_transaction_no" not in payload
        assert payload["items"][0]["amount_cents"] == 7000
    page = client.get(ROOT, params={"idempotency_key": "order"}, headers=setup.resident.headers())
    assert page.status_code == 200 and page.json()["total"] == 1
    assert (
        client.post(
            ROOT + f"/{order_id}/client-payment-parameters", headers=setup.resident.headers()
        ).status_code
        == 409
    )
    refresh = client.post(ROOT + f"/{order_id}/refreshes", headers=setup.resident.headers())
    assert refresh.status_code == 202 and refresh.headers["Cache-Control"] == "no-store"
    closure = client.post(ROOT + f"/{order_id}/closures", headers=setup.resident.headers())
    assert closure.status_code == 202 and closure.json()["status"] == "closing"
    released = client.post(
        f"/v1/miniapp-users/me/house-bindings/{setup.binding_id}/releases",
        json={"expected_row_version": 1},
        headers=setup.resident.headers(),
    )
    assert released.status_code == 200
    replay = client.post(ROOT, json=data, headers=setup.resident.headers("order"))
    assert replay.status_code == 201 and replay.json()["id"] == order_id
    assert client.get(ROOT + f"/{order_id}", headers=setup.resident.headers()).status_code == 200
    assert (
        client.get(
            f"/v1/miniapp-users/me/bills/{setup.bill_id}", headers=setup.resident.headers()
        ).status_code
        == 404
    )
    setup.resident.login("other-resident")
    assert client.get(ROOT + f"/{order_id}", headers=setup.resident.headers()).status_code == 404
    assert (
        client.get(
            ROOT, params={"idempotency_key": "order"}, headers=setup.resident.headers()
        ).json()["total"]
        == 0
    )


def test_payment_parameters_are_explicit_post_and_current_authorization_required(
    payment_house: PaymentHouse, monkeypatch: pytest.MonkeyPatch
) -> None:
    setup = payment_house
    configure(setup, monkeypatch)
    client = setup.resident.client
    result = client.post(ROOT, json=body(setup), headers=setup.resident.headers("order"))
    assert result.status_code == 201, result.text
    order_id = result.json()["id"]
    with setup.workspace.platform.factory() as db:
        order = db.get(PaymentOrder, order_id)
        assert order is not None
        order.status, order.prepay_token, order.updated_at = "payable", "private-prepay", utc_now()
        db.commit()
        before = db.scalar(select(func.count()).select_from(PaymentTask))
    parameter = client.post(
        ROOT + f"/{order_id}/client-payment-parameters", headers=setup.resident.headers()
    )
    assert parameter.status_code == 200, parameter.text
    assert parameter.json()["client_parameters"]["package"] == "prepay_id=private-prepay"
    assert parameter.headers["Cache-Control"] == "no-store"
    assert (
        client.get(
            ROOT + f"/{order_id}/client-payment-parameters", headers=setup.resident.headers()
        ).status_code
        == 405
    )
    client.get(ROOT + f"/{order_id}", headers=setup.resident.headers())
    with setup.workspace.platform.factory() as db:
        assert db.scalar(select(func.count()).select_from(PaymentTask)) == before
        assert (
            db.scalar(
                select(func.count())
                .select_from(PaymentChannelRequest)
                .where(
                    PaymentChannelRequest.operation.in_(
                        ("payment_submit", "payment_query", "payment_close")
                    )
                )
            )
            == 0
        )
    client.post(
        f"/v1/miniapp-users/me/house-bindings/{setup.binding_id}/releases",
        json={"expected_row_version": 1},
        headers=setup.resident.headers(),
    )
    assert (
        client.post(
            ROOT + f"/{order_id}/client-payment-parameters", headers=setup.resident.headers()
        ).status_code
        == 404
    )


def test_order_http_validates_single_bill_and_date_timezone(
    payment_house: PaymentHouse, monkeypatch: pytest.MonkeyPatch
) -> None:
    setup = payment_house
    configure(setup, monkeypatch)
    client = setup.resident.client
    assert (
        client.post(ROOT, json={"items": []}, headers=setup.resident.headers("zero")).status_code
        == 422
    )
    assert client.post(ROOT, json=body(setup), headers=setup.resident.headers()).status_code == 422
    assert (
        client.get(
            ROOT,
            params={"created_at_from": "2026-01-01T00:00:00"},
            headers=setup.resident.headers(),
        ).status_code
        == 422
    )
    assert (
        client.get(
            ROOT,
            params={
                "created_at_from": "2026-01-02T00:00:00Z",
                "created_at_to": "2026-01-01T00:00:00Z",
            },
            headers=setup.resident.headers(),
        ).status_code
        == 422
    )
    assert client.get(ROOT).status_code == 401
