from __future__ import annotations

import json

import pytest
from sqlalchemy import select
from tests.support.admin import NEW_PASSWORD, TEST_PASSWORD, Harness, admin, company

from backend_app.core.errors import AppError
from backend_app.models.admin import AdminAccount, AdminAuditLog
from backend_app.schemas import admin as schema
from backend_app.services.property_admin.admin import PropertyAdminService


def test_company_disabling_revokes_all_sessions_without_changing_child_status(
    harness: Harness,
) -> None:
    harness.login()
    c = company(harness)
    a, b = admin(harness, c["id"]), admin(harness, c["id"], "second")
    path = f"/v1/property-companies/{c['id']}"
    headers = harness.headers()
    with harness.factory() as db:
        svc = PropertyAdminService(db)
        with pytest.raises(AppError) as caught:
            svc.login(
                schema.AdminLogin(login_name=a["login_name"], password=TEST_PASSWORD),
                harness.store,
                "ip",
                "disabled-login",
            )
        assert caught.value.code == "auth.invalid_credentials"
    assert harness.client.patch(path, json={"enabled": True}, headers=headers).status_code == 200
    with harness.factory() as db:
        svc = PropertyAdminService(db)
        token, _ = svc.login(
            schema.AdminLogin(login_name=a["login_name"], password=TEST_PASSWORD),
            harness.store,
            "ip",
            "enabled-login",
        )
        ctx = svc.authenticate(harness.store, token)
        assert ctx.property_company_id == c["id"] and ctx.scope == "property_admin"
        versions = {
            row.id: row.session_version
            for row in db.scalars(
                select(AdminAccount).where(AdminAccount.property_company_id == c["id"])
            )
        }
    # Keep one enabled and one disabled account to check independent statuses.
    bpath = path + f"/admin-accounts/{b['id']}"
    assert harness.client.patch(bpath, json={"enabled": False}, headers=headers).status_code == 200
    with harness.factory() as db:
        account = db.get(AdminAccount, b["id"])
        assert account
        versions[b["id"]] = account.session_version
    assert harness.client.patch(path, json={"enabled": False}, headers=headers).status_code == 200
    assert harness.store.read("property_admin", token) is not None
    with harness.factory() as db:
        rows = list(
            db.scalars(select(AdminAccount).where(AdminAccount.property_company_id == c["id"]))
        )
        assert {row.id: row.enabled for row in rows} == {a["id"]: True, b["id"]: False}
        assert all(row.session_version == versions[row.id] + 1 for row in rows)
        with pytest.raises(AppError) as caught:
            PropertyAdminService(db).authenticate(harness.store, token)
        assert caught.value.code == "auth.unauthenticated"
    assert harness.client.patch(path, json={"enabled": True}, headers=headers).status_code == 200
    with harness.factory() as db:
        with pytest.raises(AppError) as caught:
            PropertyAdminService(db).authenticate(harness.store, token)
        assert caught.value.code == "auth.unauthenticated"
        new_token, _ = PropertyAdminService(db).login(
            schema.AdminLogin(login_name=a["login_name"], password=TEST_PASSWORD),
            harness.store,
            "ip",
            "reenabled-login",
        )
        assert new_token != token


def test_last_company_admin_is_protected(harness: Harness) -> None:
    harness.login()
    c = company(harness)
    a = admin(harness, c["id"])
    path = f"/v1/property-companies/{c['id']}/admin-accounts/{a['id']}"
    headers = harness.headers()
    protected = harness.client.patch(path, json={"enabled": False}, headers=headers)
    assert protected.status_code == 409 and protected.json()["code"] == "admin.last_super_admin"
    admin(harness, c["id"], "second")
    assert harness.client.patch(path, json={"enabled": False}, headers=headers).status_code == 200
    assert (
        harness.client.patch(
            path, json={"enabled": True, "display_name": "新名称"}, headers=headers
        ).status_code
        == 200
    )


def test_password_reset_while_company_disabled_is_audited(harness: Harness) -> None:
    harness.login()
    c = company(harness)
    a = admin(harness, c["id"])
    path = f"/v1/property-companies/{c['id']}/admin-accounts/{a['id']}"
    headers = harness.headers()
    with harness.factory() as db:
        account = db.get(AdminAccount, a["id"])
        assert account
        account.must_change_password = False
        before = account.session_version
        db.commit()
    reset = harness.client.post(
        path + "/password-resets", json={"password": NEW_PASSWORD}, headers=headers
    )
    assert reset.status_code == 204
    with harness.factory() as db:
        account = db.get(AdminAccount, a["id"])
        assert account and account.session_version == before + 1 and account.must_change_password
        audits = list(
            db.scalars(select(AdminAuditLog).where(AdminAuditLog.action.like("property.%")))
        )
        assert audits and all(row.scope == "platform_admin" for row in audits)
        assert all(row.property_company_id == c["id"] for row in audits)
        assert all("property_company_id" not in row.safe_metadata for row in audits)
        assert TEST_PASSWORD not in json.dumps([row.safe_metadata for row in audits])
        assert NEW_PASSWORD not in json.dumps([row.safe_metadata for row in audits])
    public_audits = harness.client.get("/v1/admin-audit-logs").json()["items"]
    assert all(
        row["property_company_id"] == c["id"] and "property_company_id" not in row["metadata"]
        for row in public_audits
        if row["action"].startswith("property.")
    )
