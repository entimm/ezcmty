import json
from hashlib import sha256
from typing import Literal

from backend_app.core.config import Settings
from backend_app.core.errors import AppError
from backend_app.models.payments import (
    ProfitSharingRuleVersion,
    ProfitSharingRuleVersionItem,
    PropertyMerchantBinding,
)
from backend_app.models.property import PropertyCompany

type ConfigurationReason = Literal[
    "company_disabled",
    "merchant_missing",
    "rule_missing",
    "merchant_unverified",
    "receiver_unready",
    "ratio_unknown",
    "ratio_exceeded",
    "channel_unavailable",
]


def fingerprint(value: object) -> str:
    return sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def configuration_token(bindings: list[tuple[str, int]], rule_id: str | None) -> str:
    return fingerprint({"bindings": sorted(bindings), "latest_rule_id": rule_id})


def channel_configured(settings: Settings) -> bool:
    return bool(
        settings.wechat_miniapp_app_id
        and settings.wechatpay_service_provider_merchant_no
        and settings.wechatpay_merchant_certificate_serial
        and settings.wechatpay_merchant_private_key.get_secret_value()
        and settings.wechatpay_api_v3_key.get_secret_value()
        and settings.wechatpay_verification_keys
        and settings.wechatpay_encryption_key_id
        and settings.wechatpay_payment_notify_url.startswith("https://")
        and settings.wechatpay_platform_receiver_name.get_secret_value()
    )


def configuration_reasons(
    company: PropertyCompany,
    binding: PropertyMerchantBinding | None,
    rule: ProfitSharingRuleVersion | None,
    items: list[ProfitSharingRuleVersionItem],
    *,
    settings: Settings,
    receiver_ready: bool,
) -> list[ConfigurationReason]:
    reasons: list[ConfigurationReason] = []
    if not company.enabled:
        reasons.append("company_disabled")
    if binding is None:
        reasons.append("merchant_missing")
    if rule is None or not items:
        reasons.append("rule_missing")
    if binding is not None:
        if binding.ratio_checked_at is None:
            reasons.append("merchant_unverified")
        if binding.max_ratio_bps is None:
            reasons.append("ratio_unknown")
        elif sum(i.rate_bps for i in items) > binding.max_ratio_bps:
            reasons.append("ratio_exceeded")
        if not receiver_ready:
            reasons.append("receiver_unready")
        if binding.service_provider_merchant_no != settings.wechatpay_service_provider_merchant_no:
            reasons.append("channel_unavailable")
    if not channel_configured(settings) and "channel_unavailable" not in reasons:
        reasons.append("channel_unavailable")
    return reasons


def validate_amount(
    amount_cents: int, items: list[ProfitSharingRuleVersionItem], max_ratio_bps: int
) -> None:
    # Each receiver rounds independently; rate-only validation misses the half-cent boundary.
    total = sum((amount_cents * i.rate_bps + 5000) // 10000 for i in items)
    if (
        not 0 < amount_cents <= 2_147_483_647
        or not items
        or sum(i.rate_bps for i in items) > max_ratio_bps
        or total * 10000 > amount_cents * max_ratio_bps
    ):
        raise AppError("payment.rate_exceeds_channel_limit")
