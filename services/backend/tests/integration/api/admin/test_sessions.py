from __future__ import annotations

import json

import pytest
from sqlalchemy import select
from tests.support.admin import NEW_PASSWORD, ORIGIN, TEST_PASSWORD, Harness

from backend_app.app_factory import create_app
from backend_app.models.admin import (
    AdminAccount,
)


def test_login_cookie_and_restricted_session(harness: Harness) -> None:
    with harness.factory() as db:
        account = db.scalar(select(AdminAccount).where(AdminAccount.login_name == "root"))
        assert account
        account.must_change_password = True
        db.commit()
    login = harness.client.post(
        "/v1/admin-sessions",
        json={"login_name": "root", "password": NEW_PASSWORD},
        headers={"Origin": ORIGIN},
    )
    assert login.status_code == 201
    assert login.json()["permissions"] == []
    cookie = login.headers["set-cookie"]
    assert "HttpOnly" in cookie and "Path=/api/platform" in cookie and "SameSite=lax" in cookie
    assert login.headers["cache-control"] == "no-store"
    for path in (
        "/v1/admin-accounts/me",
        "/v1/admin-accounts",
        "/v1/admin-roles",
        "/v1/admin-audit-logs",
    ):
        response = harness.client.get(path)
        assert (
            response.status_code == 403
            and response.json()["code"] == "auth.password_change_required"
        )
    changed = harness.client.post(
        "/v1/admin-accounts/me/password-changes",
        json={"current_password": NEW_PASSWORD, "new_password": TEST_PASSWORD},
        headers=harness.headers(),
    )
    assert changed.status_code == 204 and "Path=/api/platform" in changed.headers["set-cookie"]


@pytest.mark.parametrize(
    ("name", "password"),
    [("missing", NEW_PASSWORD), ("root", "wrong-password")],
    ids=["unknown-account", "wrong-password"],
)
def test_invalid_credentials_fail_uniformly(harness: Harness, name: str, password: str) -> None:
    response = harness.client.post(
        "/v1/admin-sessions",
        json={"login_name": name, "password": password},
        headers={"Origin": ORIGIN},
    )
    assert response.status_code == 401 and response.json()["code"] == "auth.invalid_credentials"


def test_wrong_old_password_preserves_session(harness: Harness) -> None:
    harness.login()
    response = harness.client.post(
        "/v1/admin-accounts/me/password-changes",
        json={"current_password": "wrong-password", "new_password": TEST_PASSWORD},
        headers=harness.headers(),
    )
    assert response.status_code == 409 and response.json()["code"] == "auth.invalid_old_password"
    assert harness.client.get("/v1/admin-sessions/current").status_code == 200


@pytest.mark.parametrize("case", ["missing-origin", "missing-csrf", "foreign-origin"])
def test_write_rejects_invalid_origin_or_csrf(harness: Harness, case: str) -> None:
    harness.login()
    headers = {
        "missing-origin": {},
        "missing-csrf": {"Origin": ORIGIN},
        "foreign-origin": {
            "Origin": "https://evil.test",
            "X-CSRF-Token": harness.headers()["X-CSRF-Token"],
        },
    }[case]
    response = harness.client.patch(
        "/v1/admin-accounts/me", json={"display_name": "新名称"}, headers=headers
    )
    assert response.status_code == 403 and response.json()["code"] == "auth.csrf_failed"


def test_write_accepts_valid_origin_and_csrf(harness: Harness) -> None:
    harness.login()
    response = harness.client.patch(
        "/v1/admin-accounts/me", json={"display_name": "新名称"}, headers=harness.headers()
    )
    assert response.status_code == 200


def test_multi_sessions_logout_and_cross_scope_isolation(harness: Harness) -> None:
    harness.login()
    first = harness.client.cookies.get("admin_session")
    harness.login()
    second = harness.client.cookies.get("admin_session")
    assert first and second and first != second
    assert harness.store.read("property_admin", first) is None
    assert (
        harness.client.delete("/v1/admin-sessions/current", headers=harness.headers()).status_code
        == 204
    )
    assert harness.store.read("platform_admin", second) is None
    assert harness.store.read("platform_admin", first) is not None
    assert "/v1/admin-sessions" in create_app("property-admin-api").openapi()["paths"]


def test_invalid_session_subject_returns_unauthenticated(harness: Harness) -> None:
    harness.login()
    token = harness.client.cookies.get("admin_session")
    assert token
    key = harness.store.store._key("platform_admin", token)
    raw = harness.redis.get(key)
    assert raw
    payload = json.loads(raw)
    payload["subject_id"] = "not-a-uuid"
    harness.redis.setex(key, 60, json.dumps(payload))
    response = harness.client.get("/v1/admin-sessions/current")
    assert response.status_code == 401 and response.json()["code"] == "auth.unauthenticated"
