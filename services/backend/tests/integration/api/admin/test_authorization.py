from __future__ import annotations

import pytest
from sqlalchemy import func, select
from tests.support.admin import TEST_PASSWORD, Harness

from backend_app.core.admin_security import hash_password, verify_password
from backend_app.core.errors import AppError
from backend_app.models.admin import (
    AdminAccount,
    AdminAccountRole,
    AdminAuditLog,
    AdminRole,
)
from backend_app.models.property import PropertyCompany
from backend_app.schemas import admin as schema
from backend_app.services.platform_admin.admin import PlatformAdminService


def test_role_write_rules_revocation_and_account_creation(harness: Harness) -> None:
    harness.login()
    headers = harness.headers()
    role = harness.client.post(
        "/v1/admin-roles", json={"code": "reader", "name": "只读管理员"}, headers=headers
    ).json()
    result = harness.client.put(
        f"/v1/admin-roles/{role['id']}/permissions",
        json={"permissions": ["platform.system.manage"]},
        headers=headers,
    )
    assert result.status_code == 409 and result.json()["code"] == "admin.invalid_permission"
    assert (
        harness.client.put(
            f"/v1/admin-roles/{role['id']}/permissions",
            json={"permissions": ["platform.system.read"]},
            headers=headers,
        ).status_code
        == 200
    )
    result = harness.client.post(
        "/v1/admin-accounts",
        json={
            "login_name": "reader",
            "display_name": "查询账号",
            "password": TEST_PASSWORD,
            "role_ids": [role["id"]],
        },
        headers=headers,
    )
    assert result.status_code == 201
    account = result.json()
    with harness.factory() as db:
        saved = db.get(AdminAccount, account["id"])
        assert (
            saved
            and saved.password_hash != TEST_PASSWORD
            and verify_password(saved.password_hash, TEST_PASSWORD)
        )
        saved.must_change_password = False
        db.commit()
        token, stored = harness.store.create("platform_admin", saved.id, saved.session_version)
    with harness.factory() as db:
        service = PlatformAdminService(db)
        context = service.authenticate(harness.store, token)
        assert context.permissions == ["platform.system.read"]
        with pytest.raises(AppError, match="没有操作权限"):
            service.create_role(context, schema.RoleCreate(code="illegal", name="不允许"), "test")
        db.rollback()
    assert (
        harness.client.put(
            f"/v1/admin-roles/{role['id']}/permissions", json={"permissions": []}, headers=headers
        ).status_code
        == 200
    )
    assert harness.store.read("platform_admin", token) is not None
    with harness.factory() as db:
        with pytest.raises(AppError) as caught:
            PlatformAdminService(db).authenticate(harness.store, token)
        assert caught.value.code == "auth.unauthenticated"
    audit = harness.client.get("/v1/admin-audit-logs").json()["items"]
    assert any(
        entry["target_id"] == account["id"] and entry["action"] == "account.create"
        for entry in audit
    )
    assert TEST_PASSWORD not in str(audit) and stored.csrf_token not in str(audit)


def test_super_admin_protection_and_fixed_role(harness: Harness) -> None:
    session = harness.login()
    headers = harness.headers()
    root = session["subject_id"]
    role = harness.client.get("/v1/admin-roles").json()["items"][0]
    disabled = harness.client.patch(
        f"/v1/admin-accounts/{root}", json={"enabled": False}, headers=headers
    )
    assert disabled.status_code == 409 and disabled.json()["code"] == "admin.protected_account"
    removed = harness.client.put(
        f"/v1/admin-accounts/{root}/roles", json={"role_ids": []}, headers=headers
    )
    assert removed.status_code == 409 and removed.json()["code"] == "admin.protected_account"
    fixed = harness.client.patch(
        f"/v1/admin-roles/{role['id']}", json={"enabled": False}, headers=headers
    )
    assert fixed.status_code == 409 and fixed.json()["code"] == "admin.system_role_readonly"
    with harness.factory() as db:
        with pytest.raises(AppError):
            PlatformAdminService(db).initialize_super_admin("another", "管理员", TEST_PASSWORD)
        db.rollback()
        assert db.scalar(select(func.count()).select_from(AdminAccount)) == 1


def test_disabled_roles_retained_but_cannot_be_added(harness: Harness) -> None:
    harness.login()
    headers = harness.headers()
    role = harness.client.post(
        "/v1/admin-roles", json={"code": "disabled", "name": "停用角色"}, headers=headers
    ).json()
    account = harness.client.post(
        "/v1/admin-accounts",
        json={
            "login_name": "member",
            "display_name": "成员",
            "password": TEST_PASSWORD,
            "role_ids": [role["id"]],
        },
        headers=headers,
    ).json()
    assert (
        harness.client.patch(
            f"/v1/admin-roles/{role['id']}", json={"enabled": False}, headers=headers
        ).status_code
        == 200
    )
    assert (
        harness.client.put(
            f"/v1/admin-accounts/{account['id']}/roles",
            json={"role_ids": [role["id"]]},
            headers=headers,
        ).status_code
        == 200
    )
    assert (
        harness.client.put(
            f"/v1/admin-accounts/{account['id']}/roles", json={"role_ids": []}, headers=headers
        ).status_code
        == 200
    )
    assert (
        harness.client.put(
            f"/v1/admin-accounts/{account['id']}/roles",
            json={"role_ids": [role["id"]]},
            headers=headers,
        ).status_code
        == 409
    )


def test_scope_foreign_keys_and_hidden_resources(harness: Harness) -> None:
    from sqlalchemy.exc import IntegrityError

    harness.login()
    with harness.factory() as db:
        company = PropertyCompany(code="SCOPE_TEST", name="物业公司")
        db.add(company)
        db.flush()
        property_account = AdminAccount(
            scope="property_admin",
            property_company_id=company.id,
            login_name="root",
            display_name="物业",
            password_hash=hash_password(TEST_PASSWORD),
        )
        db.add(property_account)
        db.commit()
        property_id = property_account.id
        platform_role = db.scalar(select(AdminRole).where(AdminRole.scope == "platform_admin"))
        assert platform_role
        db.add(
            AdminAccountRole(
                scope="property_admin",
                property_company_id=company.id,
                account_id=property_id,
                role_id=platform_role.id,
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
    assert harness.client.get(f"/v1/admin-accounts/{property_id}").status_code == 404
    assert all(
        entry["scope"] == "platform_admin"
        for entry in harness.client.get("/v1/admin-accounts").json()["items"]
    )
    with harness.factory() as db:
        assert db.scalar(select(func.count()).select_from(AdminAuditLog))
