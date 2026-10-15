from __future__ import annotations

from pytest import MonkeyPatch
from sqlalchemy import select
from tests.support.admin import TEST_PASSWORD, Harness

from backend_app.models.admin import (
    AdminAccount,
)


def test_account_and_audit_roll_back_together(harness: Harness, monkeypatch: MonkeyPatch) -> None:
    harness.login()
    headers = harness.headers()
    monkeypatch.setattr(
        "backend_app.repositories.admin.AdminRepository.audit",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("audit failed")),
    )
    response = harness.client.post(
        "/v1/admin-accounts",
        json={
            "login_name": "rolledback",
            "display_name": "回滚",
            "password": TEST_PASSWORD,
            "role_ids": [],
        },
        headers=headers,
    )
    assert response.status_code == 500
    with harness.factory() as db:
        assert (
            db.scalar(select(AdminAccount).where(AdminAccount.login_name == "rolledback")) is None
        )
