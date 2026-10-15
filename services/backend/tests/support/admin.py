from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from backend_app.core.admin_sessions import AdminSessionStore
from tests.support.redis import MemoryRedis

TEST_PASSWORD = "test-initial-password"
NEW_PASSWORD = "test-changed-password"
ORIGIN = "http://127.0.0.1:5173"


@dataclass
class Harness:
    client: TestClient
    factory: sessionmaker[Session]
    redis: MemoryRedis
    store: AdminSessionStore

    def login(self, name: str = "root", password: str = NEW_PASSWORD) -> dict[str, Any]:
        response = self.client.post(
            "/v1/admin-sessions",
            json={"login_name": name, "password": password},
            headers={"Origin": ORIGIN},
        )
        assert response.status_code == 201, response.text
        return cast(dict[str, Any], response.json())

    def headers(self) -> dict[str, str]:
        response = self.client.get("/v1/admin-sessions/current")
        assert response.status_code == 200
        return {"Origin": ORIGIN, "X-CSRF-Token": response.json()["csrf_token"]}


def company(h: Harness, code: str = "company") -> dict[str, Any]:
    response = h.client.post(
        "/v1/property-companies",
        json={"code": code, "name": code, "contact_name": "联系人"},
        headers=h.headers(),
    )
    assert response.status_code == 201, response.text
    return dict(response.json())


def admin(h: Harness, company_id: str, name: str = "property_root") -> dict[str, Any]:
    response = h.client.post(
        f"/v1/property-companies/{company_id}/admin-accounts",
        json={"login_name": name, "display_name": name, "password": TEST_PASSWORD},
        headers=h.headers(),
    )
    assert response.status_code == 201, response.text
    return dict(response.json())
