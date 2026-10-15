from __future__ import annotations

from typing import Any

from pytest import MonkeyPatch
from sqlalchemy import func, select
from tests.support.admin import TEST_PASSWORD, Harness, admin, company

from backend_app.models.admin import AdminAccount, AdminAccountRole, AdminRole
from backend_app.models.property import PropertyCompany
from backend_app.repositories.admin import AdminRepository


def test_admin_provisioning_rolls_back_when_audit_fails(
    harness: Harness, monkeypatch: MonkeyPatch
) -> None:
    harness.login()
    c = company(harness)

    def fail(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("audit failure")

    monkeypatch.setattr(AdminRepository, "audit", fail)
    response = harness.client.post(
        f"/v1/property-companies/{c['id']}/admin-accounts",
        json={"login_name": "rollback", "display_name": "失败", "password": TEST_PASSWORD},
        headers=harness.headers(),
    )
    assert response.status_code == 500
    with harness.factory() as db:
        assert not db.scalar(
            select(func.count())
            .select_from(AdminRole)
            .where(AdminRole.property_company_id == c["id"])
        )
        assert not db.scalar(
            select(func.count())
            .select_from(AdminAccount)
            .where(AdminAccount.property_company_id == c["id"])
        )
        assert not db.scalar(
            select(func.count())
            .select_from(AdminAccountRole)
            .where(AdminAccountRole.property_company_id == c["id"])
        )


def test_company_disable_rolls_back_when_audit_fails(
    harness: Harness, monkeypatch: MonkeyPatch
) -> None:
    harness.login()
    c = company(harness)

    def fail(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("audit failure")

    a = admin(harness, c["id"])
    path = f"/v1/property-companies/{c['id']}"
    assert (
        harness.client.patch(path, json={"enabled": True}, headers=harness.headers()).status_code
        == 200
    )
    monkeypatch.setattr(AdminRepository, "audit", fail)
    response = harness.client.patch(path, json={"enabled": False}, headers=harness.headers())
    assert response.status_code == 500
    with harness.factory() as db:
        account, target = db.get(AdminAccount, a["id"]), db.get(PropertyCompany, c["id"])
        assert account and target and account.session_version == 1 and target.enabled
