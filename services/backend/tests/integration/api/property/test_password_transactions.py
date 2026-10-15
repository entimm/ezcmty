from __future__ import annotations

from typing import Any

from pytest import MonkeyPatch
from tests.support.admin import NEW_PASSWORD, TEST_PASSWORD
from tests.support.workspace import PREFIX, WorkspaceHarness

from backend_app.core.admin_security import verify_password
from backend_app.models.admin import AdminAccount
from backend_app.repositories.admin import AdminRepository


def test_failed_audit_rolls_back_property_password_change(
    workspace: WorkspaceHarness,
    monkeypatch: MonkeyPatch,
) -> None:
    w = workspace
    w.login()
    headers = w.headers()

    def fail(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("audit storage failed")

    monkeypatch.setattr(AdminRepository, "audit", fail)
    response = w.client.post(
        f"{PREFIX}/admin-accounts/me/password-changes",
        json={"current_password": TEST_PASSWORD, "new_password": NEW_PASSWORD},
        headers=headers,
    )
    assert response.status_code == 500
    with w.platform.factory() as db:
        account = db.get(AdminAccount, w.account_id)
        assert account and account.must_change_password and account.session_version == 1
        assert verify_password(account.password_hash, TEST_PASSWORD)
    assert w.client.get(f"{PREFIX}/admin-sessions/current").status_code == 200
