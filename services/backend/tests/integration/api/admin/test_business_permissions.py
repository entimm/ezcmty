from sqlalchemy import func, select
from tests.support.admin import TEST_PASSWORD, Harness, admin, company
from tests.support.workspace import PREFIX, WorkspaceHarness

from backend_app.models.admin import AdminAccount, AdminAuditLog, AdminRole, AdminRolePermission
from backend_app.schemas import admin as schema
from backend_app.services.property_admin.admin import PropertyAdminService


def test_role_initial_permissions_are_normalized_and_account_preview_uses_enabled_union(
    harness: Harness,
) -> None:
    harness.login()
    headers = harness.headers()
    response = harness.client.post(
        "/v1/admin-roles",
        json={
            "code": "financial",
            "name": "财务经办",
            "permissions": ["platform.payment_reconciliation.manage"],
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    role = response.json()
    assert role["permissions"] == [
        "platform.payment_reconciliation.manage",
        "platform.payment_reconciliation.read",
    ]
    assert role["affected_account_count"] == 0
    account = harness.client.post(
        "/v1/admin-accounts",
        json={
            "login_name": "financial",
            "display_name": "财务",
            "password": TEST_PASSWORD,
            "role_ids": [role["id"]],
        },
        headers=headers,
    ).json()
    assert account["effective_permissions"] == role["permissions"]
    assert harness.client.get(f"/v1/admin-roles/{role['id']}").json()["affected_account_count"] == 1
    with harness.factory() as db:
        stored = list(
            db.scalars(
                select(AdminRolePermission.permission)
                .where(AdminRolePermission.role_id == role["id"])
                .order_by(AdminRolePermission.permission)
            )
        )
        assert stored == role["permissions"]
        audit = db.scalar(
            select(AdminAuditLog).where(
                AdminAuditLog.action == "role.create", AdminAuditLog.target_id == role["id"]
            )
        )
        assert audit and audit.safe_metadata["permissions"] == stored
    disabled = harness.client.patch(
        f"/v1/admin-roles/{role['id']}", json={"enabled": False}, headers=headers
    )
    assert disabled.status_code == 200
    assert (
        harness.client.get(f"/v1/admin-accounts/{account['id']}").json()["effective_permissions"]
        == []
    )


def test_invalid_initial_permissions_leave_no_role_or_audit(harness: Harness) -> None:
    harness.login()
    result = harness.client.post(
        "/v1/admin-roles",
        json={"code": "invalid", "name": "无效", "permissions": ["platform.system.manage"]},
        headers=harness.headers(),
    )
    assert result.status_code == 409 and result.json()["code"] == "admin.invalid_permission"
    with harness.factory() as db:
        assert (
            db.scalar(
                select(func.count()).select_from(AdminRole).where(AdminRole.code == "invalid")
            )
            == 0
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(AdminAuditLog)
                .where(AdminAuditLog.action == "role.create")
            )
            == 0
        )


def test_property_super_admin_manages_only_own_company_and_templates(
    workspace: WorkspaceHarness,
) -> None:
    w = workspace
    w.complete_login()
    headers = w.headers()
    templates = w.client.get(f"{PREFIX}/admin-role-templates")
    assert templates.status_code == 200, templates.text
    assert {item["name"] for item in templates.json()} == {"资料专员", "收费员", "客服审核员"}
    role_response = w.client.post(
        f"{PREFIX}/admin-roles",
        json={"code": "cashier", "name": "收费员", "permissions": ["property.bill.manage"]},
        headers=headers,
    )
    assert role_response.status_code == 201, role_response.text
    role = role_response.json()
    created = w.client.post(
        f"{PREFIX}/admin-accounts",
        json={
            "login_name": "cashier",
            "display_name": "收费员",
            "password": TEST_PASSWORD,
            "role_ids": [role["id"]],
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    assert created.json()["effective_permissions"] == ["property.bill.manage", "property.bill.read"]
    foreign_company = company(w.platform, "other-company")
    foreign = admin(w.platform, foreign_company["id"], "other_root")
    assert w.client.get(f"{PREFIX}/admin-accounts/{foreign['id']}").status_code == 404
    assert w.client.get(f"{PREFIX}/admin-roles/{foreign['roles'][0]['id']}").status_code == 404
    rejected = w.client.put(
        f"{PREFIX}/admin-accounts/{created.json()['id']}/roles",
        json={"role_ids": [foreign["roles"][0]["id"]]},
        headers=headers,
    )
    assert rejected.status_code == 409 and rejected.json()["code"] == "admin.invalid_role"
    own_accounts = w.client.get(f"{PREFIX}/admin-accounts").json()
    assert own_accounts["total"] == 2
    assert {item["id"] for item in own_accounts["items"]} == {w.account_id, created.json()["id"]}
    with w.platform.factory() as db:
        logs = list(
            db.scalars(
                select(AdminAuditLog).where(
                    AdminAuditLog.scope == "property_admin",
                    AdminAuditLog.action == "account.create",
                )
            )
        )
        assert len(logs) == 1 and logs[0].property_company_id == w.company_id
        account = db.get(AdminAccount, created.json()["id"])
        assert account and account.property_company_id == w.company_id


def test_property_system_reader_cannot_write_and_grant_change_revokes_session(
    workspace: WorkspaceHarness,
) -> None:
    w = workspace
    w.complete_login()
    role = w.client.post(
        f"{PREFIX}/admin-roles",
        json={
            "code": "reader",
            "name": "只读",
            "permissions": ["property.system.read", "property.audit.read"],
        },
        headers=w.headers(),
    ).json()
    account = w.client.post(
        f"{PREFIX}/admin-accounts",
        json={
            "login_name": "reader",
            "display_name": "只读",
            "password": TEST_PASSWORD,
            "role_ids": [role["id"]],
        },
        headers=w.headers(),
    ).json()
    with w.platform.factory() as db:
        stored = db.get(AdminAccount, account["id"])
        assert stored
        stored.must_change_password = False
        db.commit()
    w.login(TEST_PASSWORD, "reader")
    assert w.client.get(f"{PREFIX}/admin-accounts").status_code == 200
    assert w.client.get(f"{PREFIX}/admin-audit-logs").status_code == 200
    forbidden = w.client.post(
        f"{PREFIX}/admin-roles", json={"code": "forbidden", "name": "越权"}, headers=w.headers()
    )
    assert forbidden.status_code == 403
    with w.platform.factory() as db:
        stored = db.get(AdminAccount, w.account_id)
        assert stored
        token, _ = w.platform.store.create("property_admin", stored.id, stored.session_version)
    # Keep reader's cookie to verify the version invalidation after the administrator change.

    with w.platform.factory() as db:
        service = PropertyAdminService(db)
        context = service.authenticate(w.platform.store, token)
        service.set_role_permissions(
            context, role["id"], schema.PermissionSet(permissions=[]), "revoke-reader"
        )
    assert w.client.get(f"{PREFIX}/admin-sessions/current").status_code == 401
