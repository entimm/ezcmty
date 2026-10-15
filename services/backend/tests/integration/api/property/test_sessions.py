from __future__ import annotations

from tests.support.admin import NEW_PASSWORD, ORIGIN, TEST_PASSWORD, admin
from tests.support.workspace import PREFIX, WorkspaceHarness


def test_login_scope_and_company_inputs_cannot_be_selected(workspace: WorkspaceHarness) -> None:
    w = workspace
    for field, value in (("scope", "platform_admin"), ("property_company_id", w.company_id)):
        login = w.client.post(
            f"{PREFIX}/admin-sessions",
            json={"login_name": "property_root", "password": TEST_PASSWORD, field: value},
            headers={"Origin": ORIGIN},
        )
        assert login.status_code == 422
    w.complete_login()
    forged = w.client.patch(
        f"{PREFIX}/admin-accounts/me",
        json={"display_name": "改名", "property_company_id": w.company_id},
        headers=w.headers(),
    )
    assert forged.status_code == 422
    platform_cookie = w.platform.client.cookies.get("admin_session")
    property_cookie = w.client.cookies.get("admin_session")
    assert platform_cookie and property_cookie
    assert (
        w.client.get(
            f"{PREFIX}/admin-sessions/current",
            headers={"Cookie": f"admin_session={platform_cookie}"},
        ).status_code
        == 401
    )
    assert (
        w.platform.client.get(
            "/v1/admin-sessions/current", headers={"Cookie": f"admin_session={property_cookie}"}
        ).status_code
        == 401
    )
    assert w.platform.client.get("/v1/admin-sessions/current").status_code == 200


def test_disabled_company_and_account_login_fail_uniformly(workspace: WorkspaceHarness) -> None:
    w = workspace
    admin(w.platform, w.company_id, "second-admin")
    account_path = f"/v1/property-companies/{w.company_id}/admin-accounts/{w.account_id}"
    responses = []
    for name, password in (("missing", TEST_PASSWORD), ("property_root", "wrong-password")):
        responses.append(
            w.client.post(
                f"{PREFIX}/admin-sessions",
                json={"login_name": name, "password": password},
                headers={"Origin": ORIGIN},
            )
        )
    disabled = w.platform.client.patch(
        account_path, json={"enabled": False}, headers=w.platform.headers()
    )
    assert disabled.status_code == 200
    responses.append(
        w.client.post(
            f"{PREFIX}/admin-sessions",
            json={"login_name": "property_root", "password": TEST_PASSWORD},
            headers={"Origin": ORIGIN},
        )
    )
    assert (
        w.platform.client.patch(
            account_path, json={"enabled": True}, headers=w.platform.headers()
        ).status_code
        == 200
    )
    assert (
        w.platform.client.patch(
            f"/v1/property-companies/{w.company_id}",
            json={"enabled": False},
            headers=w.platform.headers(),
        ).status_code
        == 200
    )
    responses.append(
        w.client.post(
            f"{PREFIX}/admin-sessions",
            json={"login_name": "property_root", "password": TEST_PASSWORD},
            headers={"Origin": ORIGIN},
        )
    )
    assert all(
        r.status_code == 401 and r.json()["code"] == "auth.invalid_credentials" for r in responses
    )
    assert len({r.json()["detail"] for r in responses}) == 1


def test_company_and_account_reenable_and_password_reset_never_restore_old_sessions(
    workspace: WorkspaceHarness,
) -> None:
    w = workspace
    w.complete_login()
    first = w.client.cookies.get("admin_session")
    w.login(NEW_PASSWORD)
    second = w.client.cookies.get("admin_session")
    assert first and second and first != second
    company_path = f"/v1/property-companies/{w.company_id}"
    assert (
        w.platform.client.patch(
            company_path, json={"enabled": False}, headers=w.platform.headers()
        ).status_code
        == 200
    )
    assert w.platform.store.read("property_admin", first) is not None
    assert w.client.get(f"{PREFIX}/communities").status_code == 401
    assert (
        w.platform.client.patch(
            company_path, json={"enabled": True}, headers=w.platform.headers()
        ).status_code
        == 200
    )
    assert w.client.get(f"{PREFIX}/communities").status_code == 401
    for token in (first, second):
        assert (
            w.client.get(
                f"{PREFIX}/admin-sessions/current", headers={"Cookie": f"admin_session={token}"}
            ).status_code
            == 401
        )
    w.login(NEW_PASSWORD)
    admin(w.platform, w.company_id, "second-admin")
    account_path = f"{company_path}/admin-accounts/{w.account_id}"
    for enabled in (False, True):
        assert (
            w.platform.client.patch(
                account_path, json={"enabled": enabled}, headers=w.platform.headers()
            ).status_code
            == 200
        )
        assert w.client.get(f"{PREFIX}/admin-accounts/me").status_code == 401
    w.login(NEW_PASSWORD)
    assert (
        w.platform.client.post(
            account_path + "/password-resets",
            json={"password": TEST_PASSWORD},
            headers=w.platform.headers(),
        ).status_code
        == 204
    )
    assert w.client.get(f"{PREFIX}/communities").status_code == 401
    reset_login = w.login()
    assert reset_login["must_change_password"] and reset_login["permissions"] == []
    assert w.client.get(f"{PREFIX}/property-companies/current").status_code == 403


def test_password_change_revokes_other_devices_but_logout_is_current_only(
    workspace: WorkspaceHarness,
) -> None:
    w = workspace
    w.complete_login()
    other = w.client.cookies.get("admin_session")
    w.login(NEW_PASSWORD)
    assert other
    assert (
        w.client.delete(f"{PREFIX}/admin-sessions/current", headers=w.headers()).status_code == 204
    )
    assert w.client.get(f"{PREFIX}/admin-sessions/current").status_code == 401
    assert (
        w.client.get(
            f"{PREFIX}/admin-sessions/current", headers={"Cookie": f"admin_session={other}"}
        ).status_code
        == 200
    )
    w.login(NEW_PASSWORD)
    assert (
        w.client.post(
            f"{PREFIX}/admin-accounts/me/password-changes",
            json={"current_password": NEW_PASSWORD, "new_password": TEST_PASSWORD},
            headers=w.headers(),
        ).status_code
        == 204
    )
    assert (
        w.client.get(
            f"{PREFIX}/admin-sessions/current", headers={"Cookie": f"admin_session={other}"}
        ).status_code
        == 401
    )


def test_write_origin_csrf_and_property_login_rate_limit(workspace: WorkspaceHarness) -> None:
    w = workspace
    rejected = w.client.post(
        f"{PREFIX}/admin-sessions", json={"login_name": "property_root", "password": TEST_PASSWORD}
    )
    assert rejected.status_code == 403 and rejected.json()["code"] == "auth.csrf_failed"
    w.login()
    for headers in (
        {"Origin": ORIGIN},
        {"Origin": "https://evil.test", "X-CSRF-Token": w.headers()["X-CSRF-Token"]},
    ):
        denied = w.client.post(
            f"{PREFIX}/admin-accounts/me/password-changes",
            json={"current_password": TEST_PASSWORD, "new_password": NEW_PASSWORD},
            headers=headers,
        )
        assert denied.status_code == 403 and denied.json()["code"] == "auth.csrf_failed"
    w.platform.store.settings.admin_login_limit = 2
    attempts = [
        w.client.post(
            f"{PREFIX}/admin-sessions",
            json={"login_name": "rate-limited", "password": TEST_PASSWORD},
            headers={"Origin": ORIGIN},
        )
        for _ in range(2)
    ]
    assert attempts[-1].status_code == 429 and attempts[-1].json()["code"] == "auth.rate_limited"
    assert w.platform.client.get("/v1/admin-sessions/current").status_code == 200
