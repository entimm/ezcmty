from collections.abc import Sequence
from typing import Literal, cast

from backend_app.domain.admin.permissions import PermissionDefinition
from backend_app.domain.admin.types import AdminScope
from backend_app.models.admin import AdminAccount, AdminAuditLog, AdminRole
from backend_app.schemas import admin as schema


def session_view(
    account: AdminAccount, *, scope: AdminScope, permissions: list[str], csrf_token: str
) -> schema.AdminSession:
    return schema.AdminSession(
        scope=scope,
        subject_id=account.id,
        login_name=account.login_name,
        display_name=account.display_name,
        permissions=[] if account.must_change_password else permissions,
        must_change_password=account.must_change_password,
        csrf_token=csrf_token,
    )


def profile_view(account: AdminAccount) -> schema.AdminProfile:
    return schema.AdminProfile.model_validate(account)


def account_view(
    account: AdminAccount,
    *,
    scope: AdminScope,
    roles: Sequence[AdminRole],
    effective_permissions: list[str],
) -> schema.AdminAccount:
    return schema.AdminAccount(
        id=account.id,
        scope=scope,
        login_name=account.login_name,
        display_name=account.display_name,
        enabled=account.enabled,
        must_change_password=account.must_change_password,
        created_at=account.created_at,
        roles=[schema.RoleSummary.model_validate(role) for role in roles],
        effective_permissions=effective_permissions,
    )


def role_view(
    role: AdminRole, permissions: list[str], affected_account_count: int
) -> schema.AdminRole:
    return schema.AdminRole(
        id=role.id,
        code=role.code,
        name=role.name,
        enabled=role.enabled,
        is_system=role.is_system,
        permissions=permissions,
        affected_account_count=affected_account_count,
    )


def permission_view(permission: PermissionDefinition) -> schema.AdminPermission:
    return schema.AdminPermission.model_validate(permission)


def audit_page(
    records: Sequence[AdminAuditLog], total: int, *, page: int, page_size: int
) -> schema.AuditPage:
    return schema.AuditPage(
        items=[
            schema.AuditEntry(
                id=item.id,
                property_company_id=item.property_company_id,
                actor_id=item.actor_id,
                actor_name=item.actor_name,
                action=item.action,
                target_type=item.target_type,
                target_id=item.target_id,
                result=cast(Literal["success", "failure"], item.result),
                request_id=item.request_id,
                created_at=item.created_at,
                metadata=item.safe_metadata,
            )
            for item in records
        ],
        total=total,
        page=page,
        page_size=page_size,
    )
