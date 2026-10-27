from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend_app.core.config import Settings, get_settings
from backend_app.domain.client.types import ClientAuthorization
from backend_app.models.admin import utc_now
from backend_app.models.house_claims import HouseClaim, ResidentHouseBinding
from backend_app.models.miniapp import MiniappUser
from backend_app.models.payments import PaymentChannelRequest, PaymentOrder, PropertyMerchantBinding
from backend_app.repositories.payments.tasks import TaskLease, claim_tasks, ensure_task
from tests.support.billing_services import BillingSetup
from tests.support.payments import PaymentSetup, provision_payment
from tests.support.wechatpay import WechatPayHarness, payment_response


@dataclass
class OrderScenario:
    setup: BillingSetup
    payment: PaymentSetup
    bill_id: str
    context: ClientAuthorization
    now: datetime
    peer: WechatPayHarness
    settings: Settings

    def lease(self, task_type: str) -> TaskLease:
        with self.setup.factory() as db:
            ensure_task(db, task_type, self.payment.order_id, now=self.now, reactivate=True)
            leases = claim_tasks(db, now=self.now, task_types={task_type})
            assert len(leases) == 1
            db.commit()
            return leases[0]

    def fact(self, *, status: str = "SUCCESS") -> dict[str, Any]:
        with self.setup.factory() as db:
            order = db.get(PaymentOrder, self.payment.order_id)
            user = db.get(MiniappUser, self.payment.payer_user_id)
            assert order is not None and user is not None
            result = payment_response(status=status)
            result["out_trade_no"] = order.order_no
            result["payer"] = {"sp_openid": user.wechat_openid}
            result["success_time"] = self.now.isoformat()
            if status != "SUCCESS":
                result.pop("transaction_id")
                result.pop("success_time")
            return result

    def revoke(self) -> None:
        with self.setup.factory() as db:
            binding = db.scalars(
                select(ResidentHouseBinding).where(
                    ResidentHouseBinding.user_id == self.payment.payer_user_id
                )
            ).one()
            binding.status, binding.ended_at = "released", utc_now()
            binding.ended_by_user_id = self.payment.payer_user_id
            binding.row_version += 1
            db.commit()


def authorize(db: Session, setup: BillingSetup, user_id: str) -> None:
    now = utc_now()
    claim = HouseClaim(
        user_id=user_id,
        property_company_id=setup.housing.company_id,
        community_id=setup.housing.community_id,
        house_id=setup.house_id,
        house_label_snapshot="测试房屋",
        applicant_name="张三",
        applicant_phone="13800138000",
        match_status="unmatched",
        status="approved",
        reviewed_by_admin_id=setup.housing.context.account_id,
        reviewed_at=now,
        review_reason="已核实",
        idempotency_key="claim_" + user_id.replace("-", ""),
        request_fingerprint="4" * 64,
    )
    db.add(claim)
    db.flush()
    db.add(
        ResidentHouseBinding(
            user_id=user_id,
            property_company_id=setup.housing.company_id,
            community_id=setup.housing.community_id,
            house_id=setup.house_id,
            claim_application_id=claim.id,
            granted_at=now,
        )
    )


def order_scenario(setup: BillingSetup) -> OrderScenario:
    bill_id = setup.create().bill.id
    peer = WechatPayHarness()
    now = utc_now()
    peer.now = now.timestamp()
    with setup.factory() as db:
        payment = provision_payment(db, setup, bill_id=bill_id)
        authorize(db, setup, payment.payer_user_id)
        binding = db.get(PropertyMerchantBinding, payment.binding_id)
        user = db.get(MiniappUser, payment.payer_user_id)
        assert binding is not None and user is not None
        binding.enabled = True
        binding.max_ratio_bps, binding.ratio_checked_at = 3000, now
        binding.row_version += 1
        binding.updated_at = now
        db.add(
            PaymentChannelRequest(
                operation="receiver_add",
                merchant_binding_id=binding.id,
                request_snapshot={"merchant_no": binding.merchant_no},
                outcome="verified_response",
                response_snapshot={
                    "receiver_account": "1900000001",
                    "merchant_no": binding.merchant_no,
                },
                http_status=200,
                finished_at=now,
                request_id="receiver_ready",
            )
        )
        context = ClientAuthorization(user.id, user.session_version)
        db.commit()
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
    return OrderScenario(setup, payment, bill_id, context, now, peer, settings)


def unused_channel(_: httpx.Request) -> httpx.Response:
    raise AssertionError("Unexpected channel call")
