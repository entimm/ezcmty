"""In-memory protocol peer with real RSA and AES-GCM; it never contacts a merchant."""

import base64
import json
from collections.abc import Callable
from dataclasses import replace
from typing import Any

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import SecretStr

from backend_app.integrations.wechatpay.client import WechatPayClient, WechatPayConfig


class WechatPayHarness:
    def __init__(self) -> None:
        self.now = 1_792_368_000.0
        self.merchant_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.platform_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.config = WechatPayConfig(
            app_id="wx_test_app",
            service_provider_merchant_no="1900000001",
            merchant_certificate_serial="MERCHANTSERIAL",
            merchant_private_key=SecretStr(
                self.merchant_key.private_bytes(
                    serialization.Encoding.PEM,
                    serialization.PrivateFormat.PKCS8,
                    serialization.NoEncryption(),
                ).decode()
            ),
            api_v3_key=SecretStr("0123456789abcdef" * 2),
            verification_keys={
                "PUB_KEY_ID_TEST": self.platform_key.public_key()
                .public_bytes(
                    serialization.Encoding.PEM,
                    serialization.PublicFormat.SubjectPublicKeyInfo,
                )
                .decode()
            },
            encryption_key_id="PUB_KEY_ID_TEST",
            payment_notify_url="https://payments.example.test/webhooks/payment-success",
        )

    def client(
        self,
        handler: Callable[[httpx.Request], httpx.Response],
        **changes: Any,
    ) -> WechatPayClient:
        return WechatPayClient(
            replace(self.config, **changes),
            transport=httpx.MockTransport(handler),
            clock=lambda: self.now,
            nonce_factory=lambda: "request-nonce",
        )

    def headers(self, raw: bytes, *, timestamp: str | None = None) -> dict[str, str]:
        timestamp = timestamp or str(int(self.now))
        message = timestamp.encode() + b"\nresponse-nonce\n" + raw + b"\n"
        signature = self.platform_key.sign(message, padding.PKCS1v15(), hashes.SHA256())
        return {
            "Wechatpay-Serial": "PUB_KEY_ID_TEST",
            "Wechatpay-Nonce": "response-nonce",
            "Wechatpay-Timestamp": timestamp,
            "Wechatpay-Signature": base64.b64encode(signature).decode(),
            "Request-ID": "safe-request-id",
        }

    def response(self, value: dict[str, Any] | None, status: int = 200) -> httpx.Response:
        raw = json.dumps(value, ensure_ascii=False).encode() if value is not None else b""
        return httpx.Response(status, content=raw, headers=self.headers(raw))

    def notification(
        self, value: dict[str, Any], original_type: str
    ) -> tuple[bytes, dict[str, str]]:
        nonce = "123456789012"
        ciphertext = AESGCM(self.config.api_v3_key.get_secret_value().encode()).encrypt(
            nonce.encode(), json.dumps(value).encode(), b"transaction"
        )
        envelope = {
            "id": "notification-1",
            "event_type": "TRANSACTION.SUCCESS",
            "create_time": "2026-10-19T12:00:00+08:00",
            "summary": "支付成功",
            "resource_type": "encrypt-resource",
            "resource": {
                "algorithm": "AEAD_AES_256_GCM",
                "original_type": original_type,
                "nonce": nonce,
                "associated_data": "transaction",
                "ciphertext": base64.b64encode(ciphertext).decode(),
            },
        }
        raw = json.dumps(envelope, ensure_ascii=False, indent=2).encode()
        return raw, self.headers(raw)


def payment_response(*, status: str = "SUCCESS") -> dict[str, Any]:
    return {
        "sp_mchid": "1900000001",
        "sub_mchid": "1900000002",
        "sp_appid": "wx_test_app",
        "out_trade_no": "PAY202610190001",
        "trade_state": status,
        "transaction_id": "transaction-1",
        "success_time": "2026-10-19T12:00:00+08:00",
        "payer": {"sp_openid": "private-payer-openid"},
        "amount": {"total": 10000, "payer_total": 9900, "currency": "CNY"},
    }


def sharing_response(*, result: str = "SUCCESS") -> dict[str, Any]:
    return {
        "sub_mchid": "1900000002",
        "transaction_id": "transaction-1",
        "out_order_no": "PS202610190001",
        "order_id": "channel-sharing-1",
        "state": "FINISHED",
        "receivers": [
            {
                "type": "MERCHANT_ID",
                "account": "1900000001",
                "amount": 300,
                "result": result,
                "detail_id": "sharing-detail-1",
                "finish_time": "2026-10-19T12:01:00+08:00",
            }
        ],
    }
