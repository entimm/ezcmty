from collections.abc import Sequence

from backend_app.models.admin import AdminAccount, AdminRole
from backend_app.models.property import Community
from backend_app.schemas import admin as admin_schema
from backend_app.schemas import property as schema


def community_view(community: Community, company_name: str) -> schema.Community:
    return schema.Community(
        id=community.id,
        property_company_id=community.property_company_id,
        property_company_name=company_name,
        code=community.code,
        name=community.name,
        address=community.address,
        enabled=community.enabled,
        created_at=community.created_at,
        updated_at=community.updated_at,
    )


def property_admin_view(
    account: AdminAccount, roles: Sequence[AdminRole], effective_permissions: list[str]
) -> schema.PropertyAdminAccount:
    assert account.property_company_id is not None
    return schema.PropertyAdminAccount(
        id=account.id,
        scope="property_admin",
        property_company_id=account.property_company_id,
        login_name=account.login_name,
        display_name=account.display_name,
        enabled=account.enabled,
        must_change_password=account.must_change_password,
        created_at=account.created_at,
        roles=[admin_schema.RoleSummary.model_validate(role) for role in roles],
        effective_permissions=effective_permissions,
    )
