import re
from dataclasses import dataclass
from datetime import UTC, datetime
from time import time
from typing import Any

import httpx
from redis import Redis
from redis.exceptions import LockError

from backend_app.core.config import Settings
from backend_app.core.errors import AppError
from backend_app.domain.housing import normalize_owner_phone


@dataclass(frozen=True)
class VerifiedPhone:
    phone: str
    authorized_at: datetime


class WechatMiniapp:
    """Only credentials/access tokens are shared; phone exchange results are never cached."""

    def __init__(
        self, settings: Settings, redis: Redis[str], *, transport: httpx.BaseTransport | None = None
    ):
        self.settings = settings
        self.redis = redis
        self.transport = transport

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        if not self.settings.wechat_miniapp_app_id or not self.settings.wechat_miniapp_app_secret:
            raise AppError("system.dependency_unavailable")
        try:
            with httpx.Client(
                base_url="https://api.weixin.qq.com",
                timeout=httpx.Timeout(5, connect=3),
                transport=self.transport,
                follow_redirects=False,
            ) as client:
                response = client.request(method, path, **kwargs)
                response.raise_for_status()
                data = response.json()
                if not isinstance(data, dict):
                    raise ValueError("Invalid upstream response")
                return data
        except httpx.HTTPError, ValueError:
            # Raw exceptions contain query secrets. Do not propagate them to diagnostics.
            raise AppError("system.dependency_unavailable") from None

    def login(self, code: str) -> str:
        data = self._request(
            "GET",
            "/sns/jscode2session",
            params={
                "appid": self.settings.wechat_miniapp_app_id,
                "secret": self.settings.wechat_miniapp_app_secret.get_secret_value(),
                "js_code": code,
                "grant_type": "authorization_code",
            },
        )
        self._check_error(data)
        openid = data.get("openid")
        if not isinstance(openid, str) or not openid.strip() or len(openid) > 128:
            raise AppError("system.dependency_unavailable")
        return openid.strip()

    @staticmethod
    def _check_error(data: dict[str, Any]) -> None:
        code = data.get("errcode", 0)
        if code in (40029, 40163, 40013, 40226):
            raise AppError("wechat.invalid_code")
        if code != 0:
            raise AppError("system.dependency_unavailable")

    def _access_token(self, *, refresh: bool = False) -> str:
        key = f"app:wechat-miniapp:{self.settings.wechat_miniapp_app_id}:access-token"
        cached = self.redis.get(key)
        if cached and not refresh:
            return cached
        try:
            with self.redis.lock(key + ":refresh", timeout=15, blocking_timeout=1):
                cached = self.redis.get(key)
                if cached and not refresh:
                    return cached
                data = self._request(
                    "POST",
                    "/cgi-bin/stable_token",
                    json={
                        "grant_type": "client_credential",
                        "appid": self.settings.wechat_miniapp_app_id,
                        "secret": self.settings.wechat_miniapp_app_secret.get_secret_value(),
                        "force_refresh": refresh,
                    },
                )
                self._check_error(data)
                token, expiry = data.get("access_token"), data.get("expires_in")
                if (
                    not isinstance(token, str)
                    or not token
                    or type(expiry) is not int
                    or expiry <= 60
                ):
                    raise AppError("system.dependency_unavailable")
                self.redis.setex(key, expiry - 60, token)
                return token
        except LockError:
            raise AppError("system.dependency_unavailable") from None

    def verify_phone(self, code: str, openid: str) -> VerifiedPhone:
        token = self._access_token()
        data = self._request(
            "POST",
            "/wxa/business/getuserphonenumber",
            params={"access_token": token},
            json={"code": code, "openid": openid},
        )
        if data.get("errcode") in (40001, 40014, 42001):
            token = self._access_token(refresh=True)
            data = self._request(
                "POST",
                "/wxa/business/getuserphonenumber",
                params={"access_token": token},
                json={"code": code, "openid": openid},
            )
        self._check_error(data)
        try:
            info = data["phone_info"]
            watermark = info["watermark"]
            if watermark["appid"] != self.settings.wechat_miniapp_app_id:
                raise ValueError("Wrong application")
            timestamp = watermark["timestamp"]
            if type(timestamp) is not int or not time() - 600 <= timestamp <= time() + 60:
                raise ValueError("Invalid authorization time")
            if str(info["countryCode"]) != "86":
                raise AppError("wechat.unsupported_phone")
            phone = normalize_owner_phone(info["purePhoneNumber"])
            if not isinstance(phone, str) or not re.fullmatch(r"1[3-9][0-9]{9}", phone):
                raise AppError("wechat.unsupported_phone")
            return VerifiedPhone(phone, datetime.fromtimestamp(timestamp, UTC))
        except KeyError, TypeError, ValueError, OverflowError:
            raise AppError("system.dependency_unavailable") from None
