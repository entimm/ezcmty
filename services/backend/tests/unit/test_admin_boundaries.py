from collections.abc import Callable
from dataclasses import replace

import pytest
from pytest import MonkeyPatch
from sqlalchemy import select

from backend_app.core.admin_security import verify_password
from backend_app.core.errors import AppError
from backend_app.domain.admin.permissions import permission_catalog
from backend_app.models.admin import AdminAccount, AdminAuditLog
from backend_app.schemas import admin as admin_schema
from backend_app.schemas import property as property_schema
from backend_app.services.platform_admin.admin import PlatformAdminService
from backend_app.services.platform_admin.property import PropertyOnboardingService
from backend_app.services.property_admin.admin import PropertyAdminService
from backend_app.services.property_admin.workspace import PropertyWorkspaceService
from tests.unit.test_admin import NEW_PASSWORD, TEST_PASSWORD
from tests.unit.test_admin import harness as harness
from tests.unit.test_property_workspace import PREFIX, WorkspaceHarness
from tests.unit.test_property_workspace import workspace as workspace


def test_property_runtime_keeps_management_routes_absent_with_platform_permissions(
    workspace: WorkspaceHarness, monkeypatch: MonkeyPatch
) -> None:
    w = workspace
    w.complete_login()
    monkeypatch.setattr(
        "backend_app.domain.admin.identity.permission_catalog",
        lambda scope: permission_catalog("platform_admin"),
    )
    current = w.client.get(f"{PREFIX}/admin-sessions/current")
    assert current.status_code == 200
    assert "admin.account.create" in current.json()["permissions"]
    assert "property.admin.create" in current.json()["permissions"]
    headers = w.headers()
    account = f"/admin-accounts/{w.account_id}"
    role = f"/admin-roles/{w.account_id}"
    company = f"/property-companies/{w.company_id}"
    company_account = f"{company}/admin-accounts/{w.account_id}"
    for method, path in (
        ("GET", "/admin-accounts"),
        ("POST", "/admin-accounts"),
        ("GET", account),
        ("PATCH", account),
        ("POST", account + "/password-resets"),
        ("PUT", account + "/roles"),
        ("GET", "/admin-roles"),
        ("POST", "/admin-roles"),
        ("GET", role),
        ("PATCH", role),
        ("PUT", role + "/permissions"),
        ("GET", "/admin-permissions"),
        ("GET", "/admin-audit-logs"),
        ("GET", "/property-companies"),
        ("POST", "/property-companies"),
        ("GET", company),
        ("PATCH", company),
        ("GET", company + "/admin-accounts"),
        ("POST", company + "/admin-accounts"),
        ("GET", company_account),
        ("PATCH", company_account),
        ("POST", company_account + "/password-resets"),
    ):
        response = w.client.request(method, PREFIX + path, headers=headers, json={})
        assert response.status_code == 404, (method, path, response.text)
    for method, path in (
        ("POST", "/communities"),
        ("PATCH", f"/communities/{w.community_id}"),
    ):
        response = w.client.request(method, PREFIX + path, headers=headers, json={})
        assert response.status_code == 405, (method, path, response.text)
    assert w.client.get(f"{PREFIX}/property-companies/current").status_code == 200
    assert w.client.get(f"{PREFIX}/communities").json()["total"] == 1


def test_application_services_reject_other_backend_identity_with_matching_permissions(
    workspace: WorkspaceHarness,
) -> None:
    w = workspace
    w.complete_login()
    property_token = w.client.cookies.get("admin_session")
    platform_token = w.platform.client.cookies.get("admin_session")
    assert property_token and platform_token
    with w.platform.factory() as db:
        platform = PlatformAdminService(db)
        platform_context = platform.authenticate(w.platform.store, platform_token)
        property_admin = PropertyAdminService(db)
        property_context = property_admin.authenticate(w.platform.store, property_token)
        foreign = replace(property_context, permissions=platform_context.permissions)
        onboarding = PropertyOnboardingService(db)
        account_filters = dict(
            page=1, page_size=20, login_name=None, enabled=None, sort="-created_at"
        )
        operations: list[Callable[[], object]] = [
            lambda: platform.get_current_session(foreign),
            lambda: platform.get_profile(foreign),
            lambda: platform.get_account(foreign, platform_context.account_id),
            lambda: platform.get_role(foreign, w.account_id),
            lambda: platform.list_accounts(foreign, **account_filters),
            lambda: platform.list_roles(foreign),
            lambda: platform.list_permissions(foreign),
            lambda: platform.list_audit(foreign),
            lambda: platform.update_profile(
                foreign, admin_schema.ProfileUpdate(display_name="越界"), "foreign-profile"
            ),
            lambda: platform.create_role(
                foreign, admin_schema.RoleCreate(code="foreign", name="越界"), "foreign-role"
            ),
            lambda: onboarding.get_company(foreign, w.company_id),
            lambda: onboarding.list_companies(foreign),
            lambda: onboarding.get_community(foreign, w.community_id),
            lambda: onboarding.list_communities(foreign),
            lambda: onboarding.get_admin(foreign, w.company_id, w.account_id),
            lambda: onboarding.list_admins(foreign, w.company_id, **account_filters),
            lambda: onboarding.create_company(
                foreign,
                property_schema.CompanyCreate(code="foreign", name="越界"),
                "foreign-company",
            ),
            lambda: onboarding.update_admin(
                foreign,
                w.company_id,
                w.account_id,
                admin_schema.AccountUpdate(display_name="越界"),
                "foreign-account",
            ),
            lambda: property_admin.get_current_session(platform_context),
            lambda: property_admin.get_profile(platform_context),
            lambda: property_admin.update_profile(
                platform_context,
                admin_schema.ProfileUpdate(display_name="越界"),
                "foreign-profile",
            ),
            lambda: property_admin.change_password(
                platform_context,
                admin_schema.PasswordChange(
                    current_password=NEW_PASSWORD, new_password=TEST_PASSWORD
                ),
                "foreign-password",
            ),
            lambda: PropertyWorkspaceService(db).get_current_company(platform_context),
            lambda: PropertyWorkspaceService(db).list_communities(platform_context),
            lambda: PropertyWorkspaceService(db).get_community(platform_context, w.community_id),
        ]
        for operation in operations:
            with pytest.raises(AppError) as caught:
                operation()
            assert caught.value.code == "auth.forbidden"


def test_password_domain_keeps_account_and_audit_in_callers_transaction(
    workspace: WorkspaceHarness,
) -> None:
    w = workspace
    w.complete_login()
    token = w.client.cookies.get("admin_session")
    assert token
    with w.platform.factory() as db:
        service = PropertyAdminService(db)
        context = service.authenticate(w.platform.store, token)
        actor = service.identity.actor(context)
        version = actor.session_version
        service.identity.change_password(
            actor, NEW_PASSWORD, TEST_PASSWORD, "domain-password-rollback"
        )
        db.flush()
        assert actor.session_version == version + 1
        assert (
            db.scalar(
                select(AdminAuditLog).where(AdminAuditLog.request_id == "domain-password-rollback")
            )
            is not None
        )
        db.rollback()
    with w.platform.factory() as db:
        account = db.get(AdminAccount, w.account_id)
        assert account and account.session_version == version
        assert verify_password(account.password_hash, NEW_PASSWORD)
        assert (
            db.scalar(
                select(AdminAuditLog).where(AdminAuditLog.request_id == "domain-password-rollback")
            )
            is None
        )
    assert w.client.get(f"{PREFIX}/admin-sessions/current").status_code == 200
