import base64
import binascii
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from backend_app.integrations.wechatpay.client import (
    WechatPayClient,
    WechatPayError,
    cents_value,
    object_value,
    text_value,
    timestamp_value,
)
from backend_app.integrations.wechatpay.payments import parse_payment


@dataclass(frozen=True)
class VerifiedNotification:
    channel_notification_id: str
    notification_type: str
    payload: dict[str, Any]


class Notifications:
    def __init__(self, client: WechatPayClient) -> None:
        self.client = client

    def payment(self, headers: Mapping[str, str], raw_body: bytes) -> VerifiedNotification:
        notification_id, data = self._decrypt(headers, raw_body, "transaction")
        fact = parse_payment(data)
        if fact.channel_status != "SUCCESS":
            raise WechatPayError("INVALID_NOTIFICATION")
        return VerifiedNotification(notification_id, "payment_success", fact.snapshot())

    def profit_sharing(self, headers: Mapping[str, str], raw_body: bytes) -> VerifiedNotification:
        notification_id, data = self._decrypt(headers, raw_body, "profitsharing")
        receiver = object_value(data.get("receiver"))
        if text_value(receiver, "type", 32) != "MERCHANT_ID":
            raise WechatPayError("UNSUPPORTED_RECEIVER_TYPE")
        payload = {
            "service_provider_merchant_no": text_value(data, "sp_mchid", 64),
            "merchant_no": text_value(data, "sub_mchid", 64),
            "channel_transaction_no": text_value(data, "transaction_id", 64),
            "channel_order_no": text_value(data, "order_id", 64),
            "order_no": text_value(data, "out_order_no", 64),
            "receiver_type": "merchant",
            "receiver_account": text_value(receiver, "account", 128),
            "amount_cents": cents_value(receiver, "amount"),
            "finished_at": timestamp_value(text_value(data, "success_time", 64)).isoformat(),
        }
        return VerifiedNotification(notification_id, "profit_sharing", payload)

    def _decrypt(
        self,
        headers: Mapping[str, str],
        raw_body: bytes,
        original_type: Literal["transaction", "profitsharing"],
    ) -> tuple[str, dict[str, Any]]:
        if len(raw_body) > self.client.MAX_RESPONSE_BYTES:
            raise WechatPayError("INVALID_NOTIFICATION")
        # Never reserialize JSON before authenticating the original HTTP body.
        self.client.verify(headers, raw_body)
        try:
            envelope = object_value(json.loads(raw_body))
            resource = object_value(envelope.get("resource"))
            if (
                text_value(envelope, "event_type", 64) != "TRANSACTION.SUCCESS"
                or text_value(envelope, "resource_type", 64) != "encrypt-resource"
                or text_value(resource, "original_type", 32) != original_type
                or text_value(resource, "algorithm", 32) != "AEAD_AES_256_GCM"
            ):
                raise WechatPayError("INVALID_NOTIFICATION")
            timestamp_value(text_value(envelope, "create_time", 64))
            notification_id = text_value(envelope, "id", 64)
            nonce = text_value(resource, "nonce", 16).encode()
            associated_data = resource.get("associated_data", "")
            if not isinstance(associated_data, str) or len(associated_data) > 128:
                raise WechatPayError("INVALID_NOTIFICATION")
            ciphertext = base64.b64decode(
                text_value(resource, "ciphertext", 1_048_576), validate=True
            )
            plaintext = AESGCM(self.client.config.api_v3_key.get_secret_value().encode()).decrypt(
                nonce, ciphertext, associated_data.encode()
            )
            return notification_id, object_value(json.loads(plaintext))
        except InvalidTag, ValueError, binascii.Error:
            raise WechatPayError("INVALID_NOTIFICATION") from None
