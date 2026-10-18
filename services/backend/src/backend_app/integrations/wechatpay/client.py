import base64
import binascii
import hashlib
import hmac
import json
import re
import secrets
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from time import time
from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import urlencode, urlsplit

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509 import load_pem_x509_certificate
from pydantic import SecretStr

if TYPE_CHECKING:
    from backend_app.core.config import Settings

type Outcome = Literal["verified_response", "transport_unknown", "invalid_response"]


class WechatPayError(Exception):
    """Bounded diagnostics only: upstream messages and request objects contain secrets."""

    def __init__(
        self,
        code: str,
        *,
        outcome: Outcome = "invalid_response",
        http_status: int | None = None,
        channel_request_id: str | None = None,
        retry_after_seconds: int | None = None,
    ) -> None:
        self.code = code
        self.outcome = outcome
        self.http_status = http_status
        self.channel_request_id = channel_request_id
        self.retry_after_seconds = retry_after_seconds
        super().__init__(f"WeChat Pay: {code}")


@dataclass(frozen=True, repr=False)
class WechatPayConfig:
    app_id: str
    service_provider_merchant_no: str
    merchant_certificate_serial: str
    merchant_private_key: SecretStr
    api_v3_key: SecretStr
    verification_keys: Mapping[str, str]
    encryption_key_id: str
    payment_notify_url: str


@dataclass(frozen=True)
class ChannelResponse[T]:
    value: T = field(repr=False)
    http_status: int
    channel_request_id: str | None

    def map[U](self, convert: Callable[[T], U]) -> ChannelResponse[U]:
        try:
            return ChannelResponse(convert(self.value), self.http_status, self.channel_request_id)
        except WechatPayError as error:
            raise WechatPayError(
                error.code,
                outcome=error.outcome,
                http_status=self.http_status,
                channel_request_id=self.channel_request_id,
            ) from None


@dataclass(frozen=True)
class VerificationKey:
    public_key: rsa.RSAPublicKey
    valid_from: datetime | None = None
    valid_until: datetime | None = None


def object_value(value: object) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise WechatPayError("INVALID_STRUCTURE")
    return value


def text_value(data: Mapping[str, Any], key: str, maximum: int = 256) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value or len(value) > maximum or "\x00" in value:
        raise WechatPayError("INVALID_STRUCTURE")
    return value


def cents_value(data: Mapping[str, Any], key: str) -> int:
    value = data.get(key)
    if type(value) is not int or not 0 <= value <= 9_223_372_036_854_775_807:
        raise WechatPayError("INVALID_STRUCTURE")
    return value


def timestamp_value(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value)
        if result.utcoffset() is None:
            raise ValueError
        return result.astimezone(UTC)
    except ValueError:
        raise WechatPayError("INVALID_STRUCTURE") from None


def identity_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _nonce() -> str:
    return secrets.token_hex(16)


class WechatPayClient:
    """Authenticates exact wire bytes. No database, task or business state is accessed."""

    API_ORIGIN = "https://api.mch.weixin.qq.com"
    MAX_RESPONSE_BYTES = 2 * 1024 * 1024
    MAX_STATEMENT_BYTES = 64 * 1024 * 1024

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        *,
        transport: httpx.BaseTransport | None = None,
        lazy: bool = False,
    ) -> WechatPayClient:
        return cls(
            WechatPayConfig(
                app_id=settings.wechat_miniapp_app_id,
                service_provider_merchant_no=settings.wechatpay_service_provider_merchant_no,
                merchant_certificate_serial=settings.wechatpay_merchant_certificate_serial,
                merchant_private_key=settings.wechatpay_merchant_private_key,
                api_v3_key=settings.wechatpay_api_v3_key,
                verification_keys=settings.wechatpay_verification_keys,
                encryption_key_id=settings.wechatpay_encryption_key_id,
                payment_notify_url=settings.wechatpay_payment_notify_url,
            ),
            transport=transport,
            lazy=lazy,
        )

    def __init__(
        self,
        config: WechatPayConfig,
        *,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], float] = time,
        nonce_factory: Callable[[], str] = _nonce,
        lazy: bool = False,
    ) -> None:
        self.config = config
        self.transport = transport
        self.clock = clock
        self.nonce_factory = nonce_factory
        self._private_key: rsa.RSAPrivateKey
        self._verification_keys: dict[str, VerificationKey] = {}
        self._ready = False
        if not lazy:
            self._initialize()

    def _initialize(self) -> None:
        if self._ready:
            return
        config = self.config
        try:
            private_key = serialization.load_pem_private_key(
                config.merchant_private_key.get_secret_value().encode(), password=None
            )
            if not isinstance(private_key, rsa.RSAPrivateKey) or private_key.key_size < 2048:
                raise ValueError
            self._private_key = private_key
            if len(config.api_v3_key.get_secret_value().encode()) != 32:
                raise ValueError
            for key_id, pem in config.verification_keys.items():
                if not re.fullmatch(r"[A-Za-z0-9_]{1,128}", key_id):
                    raise ValueError
                material = pem.encode()
                valid_from = valid_until = None
                public_key: object
                if b"-----BEGIN CERTIFICATE-----" in material:
                    certificate = load_pem_x509_certificate(material)
                    if key_id.upper() != format(certificate.serial_number, "X"):
                        raise ValueError
                    public_key = certificate.public_key()
                    valid_from = certificate.not_valid_before_utc
                    valid_until = certificate.not_valid_after_utc
                else:
                    public_key = serialization.load_pem_public_key(material)
                if not isinstance(public_key, rsa.RSAPublicKey) or public_key.key_size < 2048:
                    raise ValueError
                self._verification_keys[key_id] = VerificationKey(
                    public_key, valid_from, valid_until
                )
            if config.encryption_key_id not in self._verification_keys:
                raise ValueError
            for value in (
                config.app_id,
                config.service_provider_merchant_no,
                config.merchant_certificate_serial,
            ):
                if not re.fullmatch(r"[A-Za-z0-9_]{1,64}", value):
                    raise ValueError
            parsed = urlsplit(config.payment_notify_url)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.fragment
            ):
                raise ValueError
        except ValueError, TypeError:
            raise WechatPayError("INVALID_CONFIGURATION") from None
        self._ready = True

    def sign(self, message: bytes) -> str:
        self._initialize()
        return base64.b64encode(
            self._private_key.sign(message, padding.PKCS1v15(), hashes.SHA256())
        ).decode("ascii")

    def verify(self, headers: Mapping[str, str], raw_body: bytes) -> None:
        self._initialize()
        normalized = {key.lower(): value for key, value in headers.items()}
        timestamp = normalized.get("wechatpay-timestamp", "")
        nonce = normalized.get("wechatpay-nonce", "")
        serial = normalized.get("wechatpay-serial", "")
        signature = normalized.get("wechatpay-signature", "")
        try:
            if not re.fullmatch(r"[0-9]{1,12}", timestamp):
                raise ValueError
            if not nonce or len(nonce) > 128 or any(char in nonce for char in "\r\n"):
                raise ValueError
            if abs(self.clock() - int(timestamp)) > 300:
                raise ValueError
            key = self._verification_keys.get(serial)
            if key is None:
                raise ValueError
            signed_at = datetime.fromtimestamp(int(timestamp), UTC)
            if key.valid_from is not None and signed_at < key.valid_from:
                raise ValueError
            if key.valid_until is not None and signed_at > key.valid_until:
                raise ValueError
            message = timestamp.encode() + b"\n" + nonce.encode() + b"\n" + raw_body + b"\n"
            key.public_key.verify(
                base64.b64decode(signature, validate=True),
                message,
                padding.PKCS1v15(),
                hashes.SHA256(),
            )
        except InvalidSignature, ValueError, binascii.Error, OverflowError:
            raise WechatPayError("INVALID_SIGNATURE") from None

    def encrypt_sensitive(self, plaintext: str) -> str:
        self._initialize()
        try:
            key = self._verification_keys[self.config.encryption_key_id]
            now = datetime.fromtimestamp(self.clock(), UTC)
            if key.valid_from is not None and now < key.valid_from:
                raise ValueError
            if key.valid_until is not None and now > key.valid_until:
                raise ValueError
            encrypted = key.public_key.encrypt(
                plaintext.encode(),
                padding.OAEP(mgf=padding.MGF1(hashes.SHA1()), algorithm=hashes.SHA1(), label=None),
            )
            return base64.b64encode(encrypted).decode("ascii")
        except ValueError:
            raise WechatPayError("INVALID_ENCRYPTION_INPUT") from None

    def request(
        self,
        method: str,
        path: str,
        *,
        body: Mapping[str, Any] | None = None,
        query: Mapping[str, str] | None = None,
        encrypted: bool = False,
    ) -> ChannelResponse[dict[str, Any]]:
        if (
            not path.startswith("/v3/")
            or any(value in path for value in ("?", "#", "\\", "..", "//"))
            or method not in {"GET", "POST"}
        ):
            raise WechatPayError("INVALID_REQUEST")
        target = path + ("?" + urlencode(query) if query else "")
        payload = (
            json.dumps(body, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
            if body is not None
            else b""
        )
        response = self._send(method, target, payload, encrypted=encrypted)
        try:
            self.verify(response.headers, response.content)
        except WechatPayError as error:
            raise WechatPayError(
                error.code,
                http_status=response.status_code,
                channel_request_id=self._request_id(response),
            ) from None
        value: dict[str, Any] = {}
        if response.content:
            try:
                value = object_value(json.loads(response.content))
            except ValueError, WechatPayError:
                raise WechatPayError(
                    "INVALID_STRUCTURE",
                    http_status=response.status_code,
                    channel_request_id=self._request_id(response),
                ) from None
        if not 200 <= response.status_code < 300:
            code = value.get("code")
            if not isinstance(code, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{0,127}", code):
                code = "UPSTREAM_ERROR"
            retry_after = response.headers.get("Retry-After", "")
            raise WechatPayError(
                code,
                outcome="verified_response",
                http_status=response.status_code,
                channel_request_id=self._request_id(response),
                retry_after_seconds=min(int(retry_after), 86400) if retry_after.isdigit() else None,
            )
        return ChannelResponse(value, response.status_code, self._request_id(response))

    def download(self, url: str, expected_digest: str) -> ChannelResponse[bytes]:
        """File responses have no signature; authenticate the digest from the signed bill API."""
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.netloc != "api.mch.weixin.qq.com"
            or parsed.path not in {"/v3/billdownload/file", "/v3/bill/downloadurl"}
            or parsed.fragment
            or not re.fullmatch(r"[a-fA-F0-9]{40}", expected_digest)
        ):
            raise WechatPayError("INVALID_DOWNLOAD_SOURCE")
        response = self._send(
            "GET", parsed.path + ("?" + parsed.query if parsed.query else ""), b"", download=True
        )
        if response.status_code != 200:
            raise WechatPayError(
                "DOWNLOAD_FAILED",
                http_status=response.status_code,
                channel_request_id=self._request_id(response),
            )
        digest = hashlib.sha1(response.content, usedforsecurity=False).hexdigest()
        if not hmac.compare_digest(digest, expected_digest.lower()):
            raise WechatPayError("STATEMENT_DIGEST_MISMATCH", http_status=response.status_code)
        return ChannelResponse(response.content, response.status_code, self._request_id(response))

    def _send(
        self,
        method: str,
        target: str,
        payload: bytes,
        *,
        encrypted: bool = False,
        download: bool = False,
    ) -> httpx.Response:
        timestamp = str(int(self.clock()))
        nonce = self.nonce_factory()
        request = httpx.Request(method, self.API_ORIGIN + target, content=payload)
        canonical_target = request.url.raw_path.decode("ascii")
        message = f"{method}\n{canonical_target}\n{timestamp}\n{nonce}\n".encode() + payload + b"\n"
        request.headers.update(
            {
                "Authorization": (
                    "WECHATPAY2-SHA256-RSA2048 "
                    f'mchid="{self.config.service_provider_merchant_no}",nonce_str="{nonce}",'
                    f'timestamp="{timestamp}",serial_no="{self.config.merchant_certificate_serial}",'
                    f'signature="{self.sign(message)}"'
                ),
                "Accept": "application/octet-stream" if download else "application/json",
                "Content-Type": "application/json",
                "User-Agent": "xlife2-wechatpay/1",
            }
        )
        if encrypted:
            request.headers["Wechatpay-Serial"] = self.config.encryption_key_id
        try:
            with httpx.Client(
                transport=self.transport,
                timeout=httpx.Timeout(10, connect=3),
                follow_redirects=False,
                trust_env=False,
            ) as client:
                response = client.send(request, stream=True)
                try:
                    maximum = self.MAX_STATEMENT_BYTES if download else self.MAX_RESPONSE_BYTES
                    chunks: list[bytes] = []
                    size = 0
                    for chunk in response.iter_bytes():
                        size += len(chunk)
                        if size > maximum:
                            raise WechatPayError(
                                "RESPONSE_TOO_LARGE", http_status=response.status_code
                            )
                        chunks.append(chunk)
                    headers = dict(response.headers)
                    headers.pop("content-encoding", None)
                    headers.pop("content-length", None)
                    return httpx.Response(
                        response.status_code, headers=headers, content=b"".join(chunks)
                    )
                finally:
                    response.close()
        except httpx.HTTPError:
            raise WechatPayError("TRANSPORT_UNKNOWN", outcome="transport_unknown") from None

    @staticmethod
    def _request_id(response: httpx.Response) -> str | None:
        value = response.headers.get("Request-ID", "")
        return value if re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", value) else None
