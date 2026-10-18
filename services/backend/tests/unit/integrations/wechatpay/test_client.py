import base64
import json
import re
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.x509.oid import NameOID
from pydantic import SecretStr
from tests.support.wechatpay import WechatPayHarness

from backend_app.integrations.wechatpay.client import WechatPayError


def test_signature_covers_exact_request_target_and_utf8_body(peer: WechatPayHarness) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        fields = dict(re.findall(r'([a-z_]+)="([^"]+)"', request.headers["Authorization"]))
        assert request.url.raw_path == b"/v3/test?value=a%2Bb+%E4%B8%AD%E6%96%87"
        assert request.content == '{"description":"物业账单"}'.encode()
        message = (
            b"POST\n"
            + request.url.raw_path
            + b"\n"
            + fields["timestamp"].encode()
            + b"\n"
            + fields["nonce_str"].encode()
            + b"\n"
            + request.content
            + b"\n"
        )
        peer.merchant_key.public_key().verify(
            base64.b64decode(fields["signature"]), message, padding.PKCS1v15(), hashes.SHA256()
        )
        assert fields["mchid"] == peer.config.service_provider_merchant_no
        assert fields["serial_no"] == peer.config.merchant_certificate_serial
        return peer.response({"ok": True})

    result = peer.client(handle).request(
        "POST", "/v3/test", query={"value": "a+b 中文"}, body={"description": "物业账单"}
    )
    assert result.value == {"ok": True}
    assert result.channel_request_id == "safe-request-id"


@pytest.mark.parametrize(
    "change", ["missing", "unknown_key", "stale", "future", "tampered", "probe"]
)
def test_untrusted_response_cannot_be_used(peer: WechatPayHarness, change: str) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        response = peer.response({"ok": True})
        if change == "missing":
            del response.headers["Wechatpay-Signature"]
        elif change == "unknown_key":
            response.headers["Wechatpay-Serial"] = "UNKNOWN"
        elif change in {"stale", "future"}:
            offset = -301 if change == "stale" else 301
            response.headers.update(
                peer.headers(response.content, timestamp=str(int(peer.now) + offset))
            )
        elif change == "tampered":
            return httpx.Response(200, content=b'{"ok":false}', headers=response.headers)
        else:
            response.headers["Wechatpay-Signature"] = "WECHATPAY/SIGNTEST/not-a-signature"
        return response

    with pytest.raises(WechatPayError) as caught:
        peer.client(handle).request("GET", "/v3/test")
    assert caught.value.code == "INVALID_SIGNATURE"
    assert caught.value.outcome == "invalid_response"


def test_certificate_serial_and_validity_are_checked(peer: WechatPayHarness) -> None:
    now = datetime.fromtimestamp(peer.now, UTC)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "isolated test peer")])
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(peer.platform_key.public_key())
        .serial_number(0x12AB)
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=1))
        .sign(peer.platform_key, hashes.SHA256())
    )
    pem = certificate.public_bytes(serialization.Encoding.PEM).decode()

    def handle(request: httpx.Request) -> httpx.Response:
        response = peer.response({"ok": True})
        response.headers["Wechatpay-Serial"] = "12AB"
        return response

    result = peer.client(handle, verification_keys={"12AB": pem}, encryption_key_id="12AB").request(
        "GET", "/v3/test"
    )
    assert result.value == {"ok": True}
    with pytest.raises(WechatPayError, match="INVALID_CONFIGURATION"):
        peer.client(handle, verification_keys={"WRONG": pem}, encryption_key_id="WRONG")


def test_rotation_accepts_each_configured_public_key(peer: WechatPayHarness) -> None:
    keys = dict(peer.config.verification_keys)
    keys["PUB_KEY_ID_PREVIOUS"] = keys["PUB_KEY_ID_TEST"]
    client = peer.client(lambda _: peer.response({}), verification_keys=keys)
    headers = peer.headers(b"{}")
    headers["Wechatpay-Serial"] = "PUB_KEY_ID_PREVIOUS"
    client.verify(headers, b"{}")


def test_sensitive_name_uses_rsa_oaep_sha1(peer: WechatPayHarness) -> None:
    client = peer.client(lambda _: peer.response({}))
    encrypted = client.encrypt_sensitive("平台公司全称")
    assert (
        peer.platform_key.decrypt(
            base64.b64decode(encrypted),
            padding.OAEP(mgf=padding.MGF1(hashes.SHA1()), algorithm=hashes.SHA1(), label=None),
        ).decode()
        == "平台公司全称"
    )


def test_transport_unknown_and_upstream_failure_are_distinct_and_redacted(
    peer: WechatPayHarness,
) -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("private-key-openid-and-token", request=request)

    with pytest.raises(WechatPayError) as caught:
        peer.client(timeout).request("POST", "/v3/test", body={"secret": "private"})
    assert caught.value.outcome == "transport_unknown"
    assert "private" not in str(caught.value)
    assert caught.value.__suppress_context__

    def failure(request: httpx.Request) -> httpx.Response:
        response = peer.response({"code": "NO_AUTH", "message": "private upstream detail"}, 403)
        response.headers["Retry-After"] = "30"
        return response

    with pytest.raises(WechatPayError) as caught:
        peer.client(failure).request("GET", "/v3/test")
    assert caught.value.code == "NO_AUTH"
    assert caught.value.outcome == "verified_response"
    assert caught.value.http_status == 403
    assert caught.value.retry_after_seconds == 30
    assert "private" not in str(caught.value)


def test_unsigned_error_is_not_a_definite_business_failure(peer: WechatPayHarness) -> None:
    with pytest.raises(WechatPayError) as caught:
        peer.client(lambda _: httpx.Response(403, json={"code": "NO_AUTH"})).request(
            "GET", "/v3/test"
        )
    assert caught.value.outcome == "invalid_response"
    assert caught.value.code == "INVALID_SIGNATURE"


def test_invalid_configuration_never_exposes_key_material(peer: WechatPayHarness) -> None:
    config = replace(peer.config, merchant_private_key=SecretStr("private malformed pem"))
    with pytest.raises(WechatPayError) as caught:
        peer.client(lambda _: peer.response({}), merchant_private_key=config.merchant_private_key)
    assert "private malformed" not in str(caught.value)
    assert "PRIVATE KEY" not in repr(peer.config)


def test_response_size_is_bounded(peer: WechatPayHarness) -> None:
    raw = json.dumps({"data": "x" * 100}).encode()
    client = peer.client(lambda _: httpx.Response(200, content=raw, headers=peer.headers(raw)))
    client.MAX_RESPONSE_BYTES = 10
    with pytest.raises(WechatPayError, match="RESPONSE_TOO_LARGE"):
        client.request("GET", "/v3/test")
