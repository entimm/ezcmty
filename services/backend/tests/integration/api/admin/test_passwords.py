from dataclasses import dataclass
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker
from tests.support.admin import NEW_PASSWORD, ORIGIN, TEST_PASSWORD, Harness, admin, company
from tests.support.workspace import PREFIX, WorkspaceHarness

from backend_app.core.admin_security import hash_password, verify_password
from backend_app.models.admin import AdminAccount, AdminAuditLog


@dataclass
class PasswordApi:
    client: TestClient
    prefix: str
    factory: sessionmaker[Session]

    def headers(self) -> dict[str, str]:
        response = self.client.get(f"{self.prefix}/admin-sessions/current")
        assert response.status_code == 200
        return {"Origin": ORIGIN, "X-CSRF-Token": response.json()["csrf_token"]}


@pytest.fixture(params=["platform", "property"])
def password_api(request: pytest.FixtureRequest, harness: Harness) -> PasswordApi:
    if request.param == "property":
        workspace = cast(WorkspaceHarness, request.getfixturevalue("workspace"))
        workspace.complete_login()
        return PasswordApi(workspace.client, PREFIX, harness.factory)
    harness.login()
    return PasswordApi(harness.client, "/v1", harness.factory)


def create_account(api: PasswordApi) -> str:
    response = api.client.post(
        f"{api.prefix}/admin-accounts",
        json={
            "login_name": "password_target",
            "display_name": "目标账号",
            "password": TEST_PASSWORD,
        },
        headers=api.headers(),
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def account_snapshot(api: PasswordApi) -> tuple[list[Any], int | None]:
    with api.factory() as db:
        accounts = list(
            db.execute(
                select(
                    AdminAccount.id,
                    AdminAccount.password_hash,
                    AdminAccount.session_version,
                    AdminAccount.must_change_password,
                    AdminAccount.enabled,
                ).order_by(AdminAccount.id)
            ).all()
        )
        return accounts, db.scalar(select(func.count()).select_from(AdminAuditLog))


@pytest.mark.parametrize("operation", ["create", "reset", "change"])
@pytest.mark.parametrize(
    "invalid_password",
    ["a" * 12 + "\n", "a" * 6 + "\r" + "a" * 6],
    ids=["trailing-lf", "middle-cr"],
)
def test_line_break_password_rejection_does_not_change_accounts_or_audit(
    password_api: PasswordApi, operation: str, invalid_password: str
) -> None:
    api = password_api
    target_id = create_account(api)
    if operation == "create":
        path = f"{api.prefix}/admin-accounts"
        payload = {
            "login_name": "invalid_target",
            "display_name": "拒绝账号",
            "password": invalid_password,
        }
    elif operation == "reset":
        path = f"{api.prefix}/admin-accounts/{target_id}/password-resets"
        payload = {"password": invalid_password}
    else:
        path = f"{api.prefix}/admin-accounts/me/password-changes"
        payload = {"current_password": NEW_PASSWORD, "new_password": invalid_password}
    before = account_snapshot(api)
    response = api.client.post(path, json=payload, headers=api.headers())
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert response.json()["errors"] == [
        {
            "location": ["body", "new_password" if operation == "change" else "password"],
            "type": "string_pattern_mismatch",
        }
    ]
    assert account_snapshot(api) == before
    assert api.client.get(f"{api.prefix}/admin-sessions/current").status_code == 200


@pytest.mark.parametrize(
    "password",
    [
        pytest.param("a" * 12, id="lowercase"),
        pytest.param(" " * 12, id="spaces"),
        pytest.param("  " + "😀" * 124 + "  ", id="maximum-unicode-with-spaces"),
    ],
)
def test_reset_password_can_login_and_change_without_altering_original_value(
    password_api: PasswordApi, password: str
) -> None:
    api = password_api
    target_id = create_account(api)
    with TestClient(api.client.app, base_url=str(api.client.base_url)) as target:
        old_login = target.post(
            f"{api.prefix}/admin-sessions",
            json={"login_name": "password_target", "password": TEST_PASSWORD},
            headers={"Origin": ORIGIN},
        )
        assert old_login.status_code == 201
        reset = api.client.post(
            f"{api.prefix}/admin-accounts/{target_id}/password-resets",
            json={"password": password},
            headers=api.headers(),
        )
        assert reset.status_code == 204
        assert target.get(f"{api.prefix}/admin-sessions/current").status_code == 401
        with api.factory() as db:
            account = db.get(AdminAccount, target_id)
            assert account and account.must_change_password and account.session_version == 2
            assert verify_password(account.password_hash, password)
            if password.strip() != password:
                assert not verify_password(account.password_hash, password.strip())
        login = target.post(
            f"{api.prefix}/admin-sessions",
            json={"login_name": "password_target", "password": password},
            headers={"Origin": ORIGIN},
        )
        assert login.status_code == 201 and login.json()["must_change_password"]
        headers = {"Origin": ORIGIN, "X-CSRF-Token": login.json()["csrf_token"]}
        same = target.post(
            f"{api.prefix}/admin-accounts/me/password-changes",
            json={"current_password": password, "new_password": password},
            headers=headers,
        )
        assert same.status_code == 409 and same.json()["code"] == "resource.conflict"
        changed = target.post(
            f"{api.prefix}/admin-accounts/me/password-changes",
            json={"current_password": password, "new_password": NEW_PASSWORD},
            headers=headers,
        )
        assert changed.status_code == 204
        assert target.get(f"{api.prefix}/admin-sessions/current").status_code == 401
        final_login = target.post(
            f"{api.prefix}/admin-sessions",
            json={"login_name": "password_target", "password": NEW_PASSWORD},
            headers={"Origin": ORIGIN},
        )
        assert final_login.status_code == 201 and not final_login.json()["must_change_password"]


@pytest.mark.parametrize("operation", ["create", "reset"])
def test_company_admin_password_inputs_reject_line_breaks_before_writing(
    harness: Harness, operation: str
) -> None:
    harness.login()
    company_record = company(harness)
    target = admin(harness, company_record["id"])
    api = PasswordApi(harness.client, "/v1", harness.factory)
    path = f"/v1/property-companies/{company_record['id']}/admin-accounts"
    payload = {"password": "a" * 12 + "\r\n"}
    if operation == "create":
        payload.update(login_name="invalid_target", display_name="拒绝账号")
    else:
        path += f"/{target['id']}/password-resets"
    before = account_snapshot(api)
    response = harness.client.post(path, json=payload, headers=harness.headers())
    assert response.status_code == 422
    assert account_snapshot(api) == before


def test_legacy_line_break_password_can_still_login_and_be_changed(
    password_api: PasswordApi,
) -> None:
    api = password_api
    target_id = create_account(api)
    legacy = " legacy\rcredential\n "
    with api.factory() as db:
        account = db.get(AdminAccount, target_id)
        assert account
        account.password_hash = hash_password(legacy)
        db.commit()
    login = api.client.post(
        f"{api.prefix}/admin-sessions",
        json={"login_name": "password_target", "password": legacy},
        headers={"Origin": ORIGIN},
    )
    assert login.status_code == 201
    changed = api.client.post(
        f"{api.prefix}/admin-accounts/me/password-changes",
        json={"current_password": legacy, "new_password": NEW_PASSWORD},
        headers=api.headers(),
    )
    assert changed.status_code == 204
