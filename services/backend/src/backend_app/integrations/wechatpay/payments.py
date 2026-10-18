import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from urllib.parse import quote

from backend_app.integrations.wechatpay.client import (
    ChannelResponse,
    WechatPayClient,
    WechatPayError,
    cents_value,
    identity_digest,
    object_value,
    text_value,
    timestamp_value,
)


@dataclass(frozen=True)
class PrepayResult:
    prepay_token: str = field(repr=False)

    def snapshot(self) -> dict[str, Any]:
        # The token is persisted only in the protected payment order field.
        return {"prepay_available": True}


@dataclass(frozen=True)
class PaymentFact:
    service_provider_merchant_no: str
    merchant_no: str
    app_id: str
    order_no: str
    channel_status: str
    channel_transaction_no: str | None
    amount_cents: int | None
    payer_total_cents: int | None
    currency: str | None
    payer_identity_digest: str | None
    paid_at: datetime | None

    @classmethod
    def from_snapshot(cls, data: dict[str, Any]) -> PaymentFact:
        """Read an already persisted authenticated fact; this does not authenticate new input."""
        status = text_value(data, "channel_status", 32)
        if status not in {
            "SUCCESS",
            "REFUND",
            "NOTPAY",
            "CLOSED",
            "REVOKED",
            "USERPAYING",
            "PAYERROR",
        }:
            raise WechatPayError("INVALID_STRUCTURE")
        digest = data.get("payer_identity_digest")
        if digest is not None and (
            not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest)
        ):
            raise WechatPayError("INVALID_STRUCTURE")
        total = cents_value(data, "amount_cents") if data.get("amount_cents") is not None else None
        payer_total = (
            cents_value(data, "payer_total_cents")
            if data.get("payer_total_cents") is not None
            else None
        )
        transaction_no = (
            text_value(data, "channel_transaction_no", 64)
            if data.get("channel_transaction_no")
            else None
        )
        paid_at = timestamp_value(text_value(data, "paid_at", 64)) if data.get("paid_at") else None
        currency = text_value(data, "currency", 16) if data.get("currency") else None
        if status == "SUCCESS" and (
            not transaction_no
            or paid_at is None
            or total is None
            or total <= 0
            or digest is None
            or currency != "CNY"
        ):
            raise WechatPayError("INVALID_STRUCTURE")
        return cls(
            text_value(data, "service_provider_merchant_no", 64),
            text_value(data, "merchant_no", 64),
            text_value(data, "app_id", 64),
            text_value(data, "order_no", 64),
            status,
            transaction_no,
            total,
            payer_total,
            currency,
            digest,
            paid_at,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "service_provider_merchant_no": self.service_provider_merchant_no,
            "merchant_no": self.merchant_no,
            "app_id": self.app_id,
            "order_no": self.order_no,
            "channel_status": self.channel_status,
            "channel_transaction_no": self.channel_transaction_no,
            "amount_cents": self.amount_cents,
            "payer_total_cents": self.payer_total_cents,
            "currency": self.currency,
            "payer_identity_digest": self.payer_identity_digest,
            "paid_at": self.paid_at.isoformat() if self.paid_at else None,
        }


def parse_payment(data: dict[str, Any]) -> PaymentFact:
    status = text_value(data, "trade_state", 32)
    if status not in {"SUCCESS", "REFUND", "NOTPAY", "CLOSED", "REVOKED", "USERPAYING", "PAYERROR"}:
        raise WechatPayError("INVALID_STRUCTURE")
    amount = object_value(data["amount"]) if "amount" in data else {}
    payer = object_value(data["payer"]) if "payer" in data else {}
    total = cents_value(amount, "total") if "total" in amount else None
    payer_total = cents_value(amount, "payer_total") if "payer_total" in amount else None
    currency = text_value(amount, "currency", 16) if "currency" in amount else None
    transaction_no = text_value(data, "transaction_id", 64) if "transaction_id" in data else None
    paid_at = (
        timestamp_value(text_value(data, "success_time", 64)) if "success_time" in data else None
    )
    payer_digest = (
        identity_digest(text_value(payer, "sp_openid", 128)) if "sp_openid" in payer else None
    )
    if currency not in {None, "CNY"} or amount.get("payer_currency", "CNY") != "CNY":
        raise WechatPayError("INVALID_STRUCTURE")
    if status == "SUCCESS" and (
        not transaction_no
        or paid_at is None
        or total is None
        or total <= 0
        or payer_digest is None
        or currency != "CNY"
    ):
        raise WechatPayError("INVALID_STRUCTURE")
    return PaymentFact(
        text_value(data, "sp_mchid", 64),
        text_value(data, "sub_mchid", 64),
        text_value(data, "sp_appid", 64),
        text_value(data, "out_trade_no", 64),
        status,
        transaction_no,
        total,
        payer_total,
        currency,
        payer_digest,
        paid_at,
    )


class Payments:
    def __init__(self, client: WechatPayClient) -> None:
        self.client = client

    def create_order(
        self,
        *,
        merchant_no: str,
        order_no: str,
        payer_openid: str,
        amount_cents: int,
        expires_at: datetime,
        description: str = "物业账单缴费",
    ) -> ChannelResponse[PrepayResult]:
        if (
            type(amount_cents) is not int
            or not 0 < amount_cents <= 2_147_483_647
            or expires_at.utcoffset() is None
            or not 0 < len(order_no) <= 32
            or not 0 < len(payer_openid) <= 128
            or not 0 < len(description.encode()) <= 127
        ):
            raise WechatPayError("INVALID_REQUEST")
        response = self.client.request(
            "POST",
            "/v3/pay/partner/transactions/jsapi",
            body={
                "sp_appid": self.client.config.app_id,
                "sp_mchid": self.client.config.service_provider_merchant_no,
                "sub_mchid": merchant_no,
                "out_trade_no": order_no,
                "description": description,
                "notify_url": self.client.config.payment_notify_url,
                "time_expire": expires_at.isoformat(timespec="seconds"),
                "amount": {"total": amount_cents, "currency": "CNY"},
                "payer": {"sp_openid": payer_openid},
                "settle_info": {"profit_sharing": True},
            },
        )
        return response.map(lambda data: PrepayResult(text_value(data, "prepay_id", 256)))

    def query_order(self, *, merchant_no: str, order_no: str) -> ChannelResponse[PaymentFact]:
        return self.client.request(
            "GET",
            "/v3/pay/partner/transactions/out-trade-no/" + quote(order_no, safe=""),
            query={
                "sp_mchid": self.client.config.service_provider_merchant_no,
                "sub_mchid": merchant_no,
            },
        ).map(parse_payment)

    def close_order(self, *, merchant_no: str, order_no: str) -> ChannelResponse[None]:
        response = self.client.request(
            "POST",
            "/v3/pay/partner/transactions/out-trade-no/" + quote(order_no, safe="") + "/close",
            body={
                "sp_mchid": self.client.config.service_provider_merchant_no,
                "sub_mchid": merchant_no,
            },
        )
        if response.http_status != 204 or response.value:
            raise WechatPayError("INVALID_STRUCTURE", http_status=response.http_status)
        return response.map(lambda _: None)

    def sign_payment_parameters(self, prepay_token: str) -> dict[str, str]:
        if not prepay_token or len(prepay_token) > 256 or any(c in prepay_token for c in "\r\n"):
            raise WechatPayError("INVALID_REQUEST")
        timestamp = str(int(self.client.clock()))
        nonce = self.client.nonce_factory()
        package = f"prepay_id={prepay_token}"
        message = f"{self.client.config.app_id}\n{timestamp}\n{nonce}\n{package}\n".encode()
        return {
            "timeStamp": timestamp,
            "nonceStr": nonce,
            "package": package,
            "signType": "RSA",
            "paySign": self.client.sign(message),
        }
