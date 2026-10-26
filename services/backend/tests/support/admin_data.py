"""Account arrangements for tests whose subject is outside account provisioning."""

from functools import lru_cache

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend_app.core.admin_security import hash_password
from backend_app.domain.admin.types import AdminScope
from backend_app.models.admin import AdminAccount, AdminAccountRole, AdminRole


@lru_cache(maxsize=8)
def _password_hash(password: str) -> str:
    return hash_password(password)


def create_super_admin(
    db: Session,
    *,
    scope: AdminScope,
    login_name: str,
    display_name: str,
    password: str,
    property_company_id: str | None = None,
    must_change_password: bool = False,
    session_version: int = 1,
) -> AdminAccount:
    """Flush independent account rows; the caller owns the transaction and session."""
    role = db.scalar(
        select(AdminRole).where(
            AdminRole.scope == scope,
            AdminRole.property_company_id == property_company_id,
            AdminRole.code == "super_admin",
        )
    )
    if role is None:
        role = AdminRole(
            scope=scope,
            property_company_id=property_company_id,
            code="super_admin",
            name="超级管理员" if scope == "platform_admin" else "公司超级管理员",
            enabled=True,
            is_system=True,
        )
        db.add(role)
        db.flush()
    account = AdminAccount(
        scope=scope,
        property_company_id=property_company_id,
        login_name=login_name,
        display_name=display_name,
        password_hash=_password_hash(password),
        must_change_password=must_change_password,
        session_version=session_version,
    )
    db.add(account)
    db.flush()
    db.add(
        AdminAccountRole(
            scope=scope,
            property_company_id=property_company_id,
            account_id=account.id,
            role_id=role.id,
        )
    )
    db.flush()
    return account
