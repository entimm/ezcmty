from collections.abc import Callable
from dataclasses import replace
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker
from tests.support.billing_services import BillingSetup

from backend_app.core.admin_sessions import AdminSessionStore
from backend_app.core.config import Settings, get_settings
from backend_app.core.errors import AppError
from backend_app.integrations.wechatpay.client import ChannelResponse
from backend_app.integrations.wechatpay.profit_sharing import ProfitSharing
from backend_app.models.admin import AdminAuditLog
from backend_app.models.payments import PaymentChannelRequest, PropertyMerchantBinding
from backend_app.models.property import PropertyCompany
from backend_app.schemas.payments import configuration as schema
from backend_app.services.platform_admin.admin import PlatformAdminService
from backend_app.services.platform_admin.payment_configuration import PaymentConfigurationService
from backend_app.services.property_admin.payment_configuration import (
    PropertyPaymentConfigurationService,
)


class ConfigurationChannel(ProfitSharing):
    def __init__(self, factory: sessionmaker[Session], company_id: str):
        self.factory = factory
        self.company_id = company_id
        self.limit = 3000
        self.calls = 0
        self.on_ratio: Callable[[], None] | None = None

    def _outside_transaction(self) -> None:
        self.calls += 1
        with self.factory() as db:
            # Both company and actor locks must have been released before HTTP.
            assert db.scalar(
                select(PropertyCompany)
                .where(PropertyCompany.id == self.company_id)
                .with_for_update(nowait=True)
            )
            assert db.scalar(select(func.count()).select_from(PaymentChannelRequest)) == self.calls

    def add_receiver(
        self,
        *,
        merchant_no: str,
        receiver_account: str,
        receiver_name: str,
        relation_type: str = "SERVICE_PROVIDER",
    ) -> ChannelResponse[dict[str, Any]]:
        self._outside_transaction()
        return ChannelResponse(
            {
                "merchant_no": merchant_no,
                "receiver_account": receiver_account,
                "receiver_type": "merchant",
            },
            200,
            None,
        )

    def maximum_ratio(self, *, merchant_no: str) -> ChannelResponse[dict[str, Any]]:
        self._outside_transaction()
        if self.on_ratio:
            self.on_ratio()
        return ChannelResponse(
            {"merchant_no": merchant_no, "maximum_ratio_bps": self.limit}, 200, None
        )


def settings() -> Settings:
    from pydantic import SecretStr

    return get_settings().model_copy(
        update={
            "wechat_miniapp_app_id": "wx_test",
            "wechatpay_service_provider_merchant_no": "sp_test",
            "wechatpay_merchant_certificate_serial": "test_serial",
            "wechatpay_merchant_private_key": SecretStr("test_only"),
            "wechatpay_api_v3_key": SecretStr("test_only"),
            "wechatpay_verification_keys": {"test_id": "test_only"},
            "wechatpay_encryption_key_id": "test_id",
            "wechatpay_payment_notify_url": "https://example.test/payment",
            "wechatpay_platform_receiver_name": SecretStr("测试平台"),
        }
    )


def test_initialization_switch_and_durable_replays(
    billing_setup: BillingSetup, real_admin: tuple[sessionmaker[Session], AdminSessionStore]
) -> None:
    setup = billing_setup
    channel = ConfigurationChannel(setup.factory, setup.housing.company_id)
    with setup.factory() as db:
        ctx = PlatformAdminService(db).authenticate(real_admin[1], setup.housing.platform_token)
        svc = PaymentConfigurationService(db, settings(), channel)
        initial = svc.get(ctx, setup.housing.company_id)
        assert not initial.ready and initial.reasons == ["merchant_missing", "rule_missing"]
        body = schema.MerchantBindingCreate(
            merchant_no="merchant_a",
            merchant_name="商户甲",
            expected_configuration_token=initial.configuration_token,
        )
        binding = svc.create_binding(ctx, setup.housing.company_id, body, "binding-a", "create-a")
        assert not binding.enabled
        current = svc.get(ctx, setup.housing.company_id)
        active = svc.activate(
            ctx,
            setup.housing.company_id,
            schema.ActiveMerchantBindingUpdate(
                binding_id=binding.id, expected_configuration_token=current.configuration_token
            ),
            "activate",
        )
        assert active.reasons == ["rule_missing"]
        rule_body = schema.ProfitSharingRuleCreate(
            expected_configuration_token=active.configuration_token,
            items=[schema.ProfitSharingRuleItemCreate(rate_bps=300)],
        )
        rule = svc.create_rule(ctx, setup.housing.company_id, rule_body, "rule-a", "rule")
        assert svc.get(ctx, setup.housing.company_id).ready
        before = svc.get(ctx, setup.housing.company_id)
        body_b = schema.MerchantBindingCreate(
            merchant_no="merchant_b",
            merchant_name="商户乙",
            expected_configuration_token=before.configuration_token,
        )
        binding_b = svc.create_binding(
            ctx, setup.housing.company_id, body_b, "binding-b", "create-b"
        )
        channel.limit = 100
        before = svc.get(ctx, setup.housing.company_id)
        switched = svc.activate(
            ctx,
            setup.housing.company_id,
            schema.ActiveMerchantBindingUpdate(
                binding_id=binding_b.id, expected_configuration_token=before.configuration_token
            ),
            "switch",
        )
        assert switched.reasons == ["ratio_exceeded"]
        calls = channel.calls
        assert (
            svc.create_binding(ctx, setup.housing.company_id, body, "binding-a", "replay").enabled
            is False
        )
        assert (
            svc.create_rule(ctx, setup.housing.company_id, rule_body, "rule-a", "replay").id
            == rule.id
        )
        assert channel.calls == calls
        current_binding = svc.get(ctx, setup.housing.company_id).current_binding
        assert current_binding and current_binding.id == binding_b.id
        with pytest.raises(AppError, match="幂等键"):
            svc.create_binding(
                ctx,
                setup.housing.company_id,
                body.model_copy(update={"merchant_name": "改名"}),
                "binding-a",
                "conflict",
            )
        db.rollback()
        disabled = svc.activate(
            ctx,
            setup.housing.company_id,
            schema.ActiveMerchantBindingUpdate(
                binding_id=None, expected_configuration_token=switched.configuration_token
            ),
            "stop",
        )
        restored = svc.activate(
            ctx,
            setup.housing.company_id,
            schema.ActiveMerchantBindingUpdate(
                binding_id=binding_b.id, expected_configuration_token=disabled.configuration_token
            ),
            "resume",
        )
        assert restored.configuration_token != switched.configuration_token
        with pytest.raises(AppError) as stale:
            svc.activate(
                ctx,
                setup.housing.company_id,
                schema.ActiveMerchantBindingUpdate(
                    binding_id=None, expected_configuration_token=switched.configuration_token
                ),
                "stale",
            )
        assert stale.value.code == "payment.configuration_changed"


def test_external_verification_rechecks_token_and_keeps_evidence(
    billing_setup: BillingSetup, real_admin: tuple[sessionmaker[Session], AdminSessionStore]
) -> None:
    setup = billing_setup
    channel = ConfigurationChannel(setup.factory, setup.housing.company_id)
    with setup.factory() as db:
        ctx = PlatformAdminService(db).authenticate(real_admin[1], setup.housing.platform_token)
        svc = PaymentConfigurationService(db, settings(), channel)
        token = svc.get(ctx, setup.housing.company_id).configuration_token
        binding = svc.create_binding(
            ctx,
            setup.housing.company_id,
            schema.MerchantBindingCreate(
                merchant_no="merchant", merchant_name="商户", expected_configuration_token=token
            ),
            "binding",
            "create",
        )
        token = svc.get(ctx, setup.housing.company_id).configuration_token

        def concurrent_change() -> None:
            with setup.factory() as other:
                item = other.get(PropertyMerchantBinding, binding.id)
                assert item
                item.enabled = True
                item.row_version += 1
                other.commit()

        channel.on_ratio = concurrent_change
        with pytest.raises(AppError) as error:
            svc.activate(
                ctx,
                setup.housing.company_id,
                schema.ActiveMerchantBindingUpdate(
                    binding_id=binding.id, expected_configuration_token=token
                ),
                "concurrent",
            )
        assert error.value.code == "payment.configuration_changed"
        db.rollback()
        assert (
            db.scalar(
                select(func.count())
                .select_from(PaymentChannelRequest)
                .where(PaymentChannelRequest.outcome == "verified_response")
            )
            == 2
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(AdminAuditLog)
                .where(AdminAuditLog.action == "payment.merchant_binding.activate")
            )
            == 0
        )


def test_property_readonly_and_permissions(billing_setup: BillingSetup) -> None:
    setup = billing_setup
    with setup.factory() as db:
        svc = PropertyPaymentConfigurationService(db, settings())
        assert svc.get(setup.housing.context).property_company_id == setup.housing.company_id
        denied = replace(setup.housing.context, permissions=[])
        with pytest.raises(AppError) as error:
            svc.get(denied)
        assert error.value.code == "auth.forbidden"
        with pytest.raises(AppError):
            PaymentConfigurationService(db, settings()).get(
                setup.housing.context, setup.housing.company_id
            )
