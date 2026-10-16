from time import time
from typing import Any, cast

import httpx
import pytest
from pydantic import SecretStr
from redis import Redis

from backend_app.core.config import Settings
from backend_app.core.errors import AppError
from backend_app.integrations.wechat_miniapp import WechatMiniapp
from tests.support.redis import MemoryRedis


def gateway(handler: Any) -> tuple[WechatMiniapp, MemoryRedis]:
    redis = MemoryRedis()
    settings = Settings(
        wechat_miniapp_app_id="test-app",
        wechat_miniapp_app_secret=SecretStr("test-secret"),
        database_url=SecretStr("postgresql+psycopg://test:test@localhost/test"),
        redis_url=SecretStr("redis://localhost:6379/0"),
    )
    return WechatMiniapp(
        settings, cast("Redis[str]", redis), transport=httpx.MockTransport(handler)
    ), redis


def test_phone_exchange_checks_current_openid_and_caches_only_access_token() -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/cgi-bin/stable_token":
            return httpx.Response(200, json={"access_token": "token", "expires_in": 7200})
        assert request.content == b'{"code":"one-use-code","openid":"current-user"}'
        return httpx.Response(
            200,
            json={
                "phone_info": {
                    "purePhoneNumber": "13800138000",
                    "countryCode": "86",
                    "watermark": {"appid": "test-app", "timestamp": int(time())},
                }
            },
        )

    wechat, redis = gateway(handle)
    assert wechat.verify_phone("one-use-code", "current-user").phone == "13800138000"
    assert len(requests) == 2
    assert [item[0] for item in redis.values.values()] == ["token"]


@pytest.mark.parametrize(
    "change,code",
    [
        (
            {"watermark": {"appid": "other-app", "timestamp": int(time())}},
            "system.dependency_unavailable",
        ),
        ({"countryCode": "852"}, "wechat.unsupported_phone"),
        ({"purePhoneNumber": "bad"}, "wechat.unsupported_phone"),
        ({"watermark": {"appid": "test-app", "timestamp": 0}}, "system.dependency_unavailable"),
    ],
)
def test_invalid_wechat_phone_results_are_never_accepted(change: dict[str, Any], code: str) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/cgi-bin/stable_token":
            return httpx.Response(200, json={"access_token": "token", "expires_in": 7200})
        return httpx.Response(
            200,
            json={
                "phone_info": {
                    "purePhoneNumber": "13800138000",
                    "countryCode": "86",
                    "watermark": {"appid": "test-app", "timestamp": int(time())},
                    **change,
                }
            },
        )

    wechat, _ = gateway(handle)
    with pytest.raises(AppError) as caught:
        wechat.verify_phone("code", "user")
    assert caught.value.code == code


def test_wechat_transport_failure_does_not_expose_secrets() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("raw-secret-in-error", request=request)

    wechat, _ = gateway(handle)
    with pytest.raises(AppError) as caught:
        wechat.login("sensitive-code")
    assert caught.value.code == "system.dependency_unavailable"
    assert caught.value.__suppress_context__
