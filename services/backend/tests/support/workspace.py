from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi.testclient import TestClient

from tests.support.admin import NEW_PASSWORD, ORIGIN, TEST_PASSWORD, Harness

PREFIX = "/api/property/v1"


@dataclass
class WorkspaceHarness:
    client: TestClient
    platform: Harness
    company_id: str
    account_id: str
    community_id: str

    def login(self, password: str = TEST_PASSWORD, name: str = "property_root") -> dict[str, Any]:
        response = self.client.post(
            f"{PREFIX}/admin-sessions",
            json={"login_name": name, "password": password},
            headers={"Origin": ORIGIN},
        )
        assert response.status_code == 201, response.text
        return dict(response.json())

    def headers(self) -> dict[str, str]:
        session = self.client.get(f"{PREFIX}/admin-sessions/current")
        assert session.status_code == 200, session.text
        return {"Origin": ORIGIN, "X-CSRF-Token": session.json()["csrf_token"]}

    def complete_login(self) -> None:
        self.login()
        response = self.client.post(
            f"{PREFIX}/admin-accounts/me/password-changes",
            json={"current_password": TEST_PASSWORD, "new_password": NEW_PASSWORD},
            headers=self.headers(),
        )
        assert response.status_code == 204, response.text
        self.login(NEW_PASSWORD)


def create_community(h: Harness, company_id: str, code: str) -> dict[str, Any]:
    response = h.client.post(
        "/v1/communities",
        json={
            "property_company_id": company_id,
            "code": code,
            "name": code,
            "address": "测试地址",
        },
        headers=h.headers(),
    )
    assert response.status_code == 201, response.text
    return dict(response.json())
