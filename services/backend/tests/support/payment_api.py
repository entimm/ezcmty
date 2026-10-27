from dataclasses import dataclass

import pytest
from pydantic import SecretStr

from backend_app.core.config import Settings, get_settings
from backend_app.models.admin import utc_now
from backend_app.models.housing import House
from backend_app.models.payments import (
    PaymentChannelRequest,
    ProfitSharingRuleVersion,
    ProfitSharingRuleVersionItem,
    PropertyMerchantBinding,
)
from backend_app.services.property_admin.admin import PropertyAdminService
from tests.support.billing_services import BillingSetup
from tests.support.housing_services import HousingSetup
from tests.support.resident import ResidentHarness
from tests.support.wechatpay import WechatPayHarness
from tests.support.workspace import WorkspaceHarness


@dataclass(frozen=True)
class PaymentHouse:
    workspace: WorkspaceHarness
    resident: ResidentHarness
    house_id: str
    binding_id: str
    bill_id: str


def billing_setup_for_house(house: PaymentHouse) -> BillingSetup:
    workspace = house.workspace
    token = workspace.client.cookies.get("admin_session")
    assert token
    platform_token = workspace.platform.client.cookies.get("admin_session")
    assert platform_token
    with workspace.platform.factory() as db:
        ctx = PropertyAdminService(db).authenticate(workspace.platform.store, token)
        model = db.get(House, house.house_id)
        assert model
        housing = HousingSetup(
            platform_token,
            token,
            ctx,
            workspace.company_id,
            workspace.community_id,
            model.space_node_id,
        )
    return BillingSetup(workspace.platform.factory, housing, house.house_id)


def configure_payment_api(
    setup: PaymentHouse, monkeypatch: pytest.MonkeyPatch
) -> tuple[WechatPayHarness, Settings]:
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
    monkeypatch.setattr("backend_app.api.client.resident.payments.get_settings", lambda: settings)
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
    return peer, settings
