from dataclasses import dataclass, field
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from backend_app.core.client_sessions import ClientSessionStore
from backend_app.core.errors import AppError
from backend_app.integrations.wechat_miniapp import VerifiedPhone, WechatMiniapp


class FakeWechat(WechatMiniapp):
    def __init__(self) -> None:
        self.phones: dict[str, str] = {}
        self.used: set[str] = set()
        self.exchanges: list[tuple[str, str]] = []

    def login(self, code: str) -> str:
        if code == "invalid":
            raise AppError("wechat.invalid_code")
        return "openid-" + code

    def verify_phone(self, code: str, openid: str) -> VerifiedPhone:
        self.exchanges.append((code, openid))
        if code in self.used or code not in self.phones:
            raise AppError("wechat.invalid_code")
        self.used.add(code)
        return VerifiedPhone(self.phones[code], datetime.now(UTC))


@dataclass
class ResidentHarness:
    client: TestClient
    store: ClientSessionStore
    wechat: FakeWechat
    token: str = ""
    user_id: str = ""
    counter: int = field(default=0)

    def login(self, code: str = "resident") -> None:
        response = self.client.post("/v1/client-sessions", json={"code": code})
        assert response.status_code == 201, response.text
        self.token = response.json()["token"]
        self.user_id = response.json()["user"]["id"]

    def headers(self, key: str | None = None) -> dict[str, str]:
        return {
            "Authorization": "Bearer " + self.token,
            "X-Client-Identity": "resident",
            **({"Idempotency-Key": key} if key else {}),
        }

    def phone(self, number: str = "13800138000") -> dict[str, object]:
        self.counter += 1
        code = f"phone-{self.counter}"
        self.wechat.phones[code] = number
        response = self.client.post(
            "/v1/miniapp-users/me/phone-bindings", json={"code": code}, headers=self.headers(code)
        )
        assert response.status_code == 201, response.text
        return response.json()  # type: ignore[no-any-return]
