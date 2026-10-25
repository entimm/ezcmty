"""Shared account and role use cases; each runtime binds its own scope and identity."""

from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend_app.core.admin_security import hash_password
from backend_app.core.errors import AppError
from backend_app.db.errors import is_unique_violation
from backend_app.domain.admin.identity import AdminIdentity
from backend_app.domain.admin.permissions import (
    normalize_permissions,
    permission_catalog,
    permission_prefix,
    role_templates,
)
from backend_app.models.admin import AdminAccount, AdminRole
from backend_app.repositories.admin import AdminRepository
from backend_app.repositories.property import PropertyRepository
from backend_app.schemas import admin as schema
from backend_app.schemas.mappers import admin as views
from backend_app.services.contracts.admin import AdminContext


class AdminManagementService:
    def __init__(self, db: Session, scope: schema.AdminScope):
        self.db = db
        self.scope = scope
        self.repo = AdminRepository(db, scope)
        self.identity = AdminIdentity(self.repo)

    @property
    def system_read_permission(self) -> str:
        return f"{permission_prefix(self.scope)}.system.read"

    def _bind_management_context(self, context: AdminContext, *, writing: bool = False) -> None:
        if context.scope != self.scope:
            raise AppError("auth.forbidden")
        self.repo.property_company_id = context.property_company_id
        self.identity.require_full_session(context)
        if self.scope == "property_admin":
            if context.property_company_id is None:
                raise AppError("auth.forbidden")
            company = PropertyRepository(self.db).company(context.property_company_id, lock=writing)
            if company is None or not company.enabled:
                raise AppError("auth.unauthenticated")

    def _management_writer(self, context: AdminContext) -> tuple[AdminAccount, AdminRole]:
        self._bind_management_context(context, writing=True)
        return self.identity.management_writer(context)

    def _account_view(self, account: AdminAccount) -> schema.AdminAccount:
        return views.account_view(
            account,
            scope=self.scope,
            roles=self.repo.account_roles(account.id),
            effective_permissions=self.identity.effective_permissions(account.id),
        )

    def _role_view(self, role: AdminRole) -> schema.AdminRole:
        return views.role_view(
            role, self.identity.role_permissions(role), self.repo.role_account_count(role.id)
        )

    def get_account(self, context: AdminContext, account_id: str) -> schema.AdminAccount:
        self._bind_management_context(context)
        self.identity.require_permission(context, self.system_read_permission)
        return self._account_view(self.identity.account(account_id))

    def get_role(self, context: AdminContext, role_id: str) -> schema.AdminRole:
        self._bind_management_context(context)
        self.identity.require_permission(context, self.system_read_permission)
        return self._role_view(self.identity.role(role_id))

    def list_permissions(self, context: AdminContext) -> list[schema.AdminPermission]:
        self._bind_management_context(context)
        self.identity.require_permission(context, self.system_read_permission)
        return [views.permission_view(item) for item in permission_catalog(self.scope)]

    def list_audit(self, context: AdminContext, **filters: Any) -> schema.AuditPage:
        self._bind_management_context(context)
        items, total = self.identity.audit.list_logs(context, **filters)
        return views.audit_page(items, total, page=filters["page"], page_size=filters["page_size"])

    def _validated_roles(self, role_ids: list[str], current: set[str] | None = None) -> set[str]:
        ids = set(role_ids)
        for role_id in sorted(ids):
            role = self.repo.role(role_id, lock=True)
            if role is None or (not role.enabled and role_id not in (current or set())):
                raise AppError("admin.invalid_role")
        return ids

    def create_account(
        self, context: AdminContext, data: schema.AccountCreate, request_id: str
    ) -> schema.AdminAccount:
        actor, _ = self._management_writer(context)
        if self.repo.identity_by_login(data.login_name):
            raise AppError("admin.duplicate_login")
        ids = self._validated_roles(data.role_ids)
        account = AdminAccount(
            scope=self.scope,
            property_company_id=self.repo.property_company_id,
            login_name=data.login_name,
            display_name=data.display_name,
            password_hash=hash_password(data.password),
        )
        self.db.add(account)
        try:
            self.db.flush()
        except IntegrityError as exc:
            self.db.rollback()
            if is_unique_violation(exc, "uq_admin_account_login"):
                raise AppError("admin.duplicate_login") from exc
            raise
        self.repo.replace_roles(account.id, ids)
        self.identity.audit.record(
            actor=actor,
            action="account.create",
            target_type="account",
            target_id=account.id,
            request_id=request_id,
            metadata={"role_ids": sorted(ids)},
        )
        self.db.commit()
        return self._account_view(account)

    def update_account(
        self, context: AdminContext, account_id: str, data: schema.AccountUpdate, request_id: str
    ) -> schema.AdminAccount:
        actor, system_role = self._management_writer(context)
        account = self.identity.account(account_id, lock=True)
        changes: list[str] = []
        if data.enabled is not None and data.enabled != account.enabled:
            if not data.enabled:
                if account.id == actor.id:
                    raise AppError("admin.protected_account")
                supers = self.repo.active_super_accounts(system_role.id)
                if any(item.id == account.id for item in supers) and len(supers) <= 1:
                    raise AppError("admin.last_super_admin")
            account.enabled = data.enabled
            account.session_version += 1
            changes.append("enabled")
        if data.display_name is not None and data.display_name != account.display_name:
            account.display_name = data.display_name
            changes.append("display_name")
        self.identity.audit.record(
            actor=actor,
            action="account.update",
            target_type="account",
            target_id=account.id,
            request_id=request_id,
            metadata={"changed_fields": changes},
        )
        self.db.commit()
        return self._account_view(account)

    def set_account_roles(
        self, context: AdminContext, account_id: str, data: schema.RoleSet, request_id: str
    ) -> schema.AdminAccount:
        actor, system_role = self._management_writer(context)
        account = self.identity.account(account_id, lock=True)
        current = {role.id for role in self.repo.account_roles(account.id, lock=True)}
        ids = self._validated_roles(data.role_ids, current)
        if system_role.id in current and system_role.id not in ids:
            if account.id == actor.id:
                raise AppError("admin.protected_account")
            supers = self.repo.active_super_accounts(system_role.id)
            if account.enabled and len(supers) <= 1:
                raise AppError("admin.last_super_admin")
        if ids != current:
            self.repo.replace_roles(account.id, ids)
            account.session_version += 1
        self.identity.audit.record(
            actor=actor,
            action="account.assign_roles",
            target_type="account",
            target_id=account.id,
            request_id=request_id,
            metadata={"role_ids": sorted(ids)},
        )
        self.db.commit()
        return self._account_view(account)

    def reset_password(
        self, context: AdminContext, account_id: str, data: schema.PasswordReset, request_id: str
    ) -> None:
        actor, _ = self._management_writer(context)
        account = self.identity.account(account_id, lock=True)
        if actor.id == account.id:
            raise AppError("resource.conflict", public_detail="请通过个人中心修改本人密码")
        account.password_hash = hash_password(data.password)
        account.must_change_password = True
        account.session_version += 1
        self.identity.audit.record(
            actor=actor,
            action="account.password_reset",
            target_type="account",
            target_id=account.id,
            request_id=request_id,
        )
        self.db.commit()

    def create_role(
        self, context: AdminContext, data: schema.RoleCreate, request_id: str
    ) -> schema.AdminRole:
        actor, _ = self._management_writer(context)
        if self.repo.role_by_code(data.code):
            raise AppError("admin.duplicate_role")
        codes = normalize_permissions(self.scope, data.permissions)
        role = AdminRole(
            scope=self.scope,
            property_company_id=self.repo.property_company_id,
            code=data.code,
            name=data.name,
        )
        self.db.add(role)
        self.db.flush()
        self.repo.replace_permissions(role.id, set(codes))
        self.identity.audit.record(
            actor=actor,
            action="role.create",
            target_type="role",
            target_id=role.id,
            request_id=request_id,
            metadata={"permissions": codes},
        )
        self.db.commit()
        return self._role_view(role)

    def update_role(
        self, context: AdminContext, role_id: str, data: schema.RoleUpdate, request_id: str
    ) -> schema.AdminRole:
        actor, _ = self._management_writer(context)
        role = self.identity.role(role_id, lock=True)
        if role.is_system:
            raise AppError("admin.system_role_readonly")
        changes: list[str] = []
        if data.name is not None and data.name != role.name:
            role.name = data.name
            changes.append("name")
        if data.enabled is not None and data.enabled != role.enabled:
            role.enabled = data.enabled
            self.repo.invalidate_role_accounts(role.id)
            changes.append("enabled")
        self.identity.audit.record(
            actor=actor,
            action="role.update",
            target_type="role",
            target_id=role.id,
            request_id=request_id,
            metadata={"changed_fields": changes},
        )
        self.db.commit()
        return self._role_view(role)

    def set_role_permissions(
        self, context: AdminContext, role_id: str, data: schema.PermissionSet, request_id: str
    ) -> schema.AdminRole:
        actor, _ = self._management_writer(context)
        role = self.identity.role(role_id, lock=True)
        if role.is_system:
            raise AppError("admin.system_role_readonly")
        codes = set(normalize_permissions(self.scope, data.permissions))
        if codes != set(self.repo.permissions(role.id, lock=True)):
            self.repo.replace_permissions(role.id, codes)
            self.repo.invalidate_role_accounts(role.id)
        self.identity.audit.record(
            actor=actor,
            action="role.assign_permissions",
            target_type="role",
            target_id=role.id,
            request_id=request_id,
            metadata={"permissions": sorted(codes)},
        )
        self.db.commit()
        return self._role_view(role)

    def list_accounts(self, context: AdminContext, **filters: Any) -> schema.AccountPage:
        self._bind_management_context(context)
        self.identity.require_permission(context, self.system_read_permission)
        items, total = self.repo.accounts(**filters)
        return schema.AccountPage(
            items=[self._account_view(item) for item in items],
            total=total,
            page=filters["page"],
            page_size=filters["page_size"],
        )

    def list_roles(self, context: AdminContext, **filters: Any) -> schema.RolePage:
        self._bind_management_context(context)
        self.identity.require_permission(context, self.system_read_permission)
        items, total = self.repo.roles(**filters)
        return schema.RolePage(
            items=[self._role_view(item) for item in items],
            total=total,
            page=filters["page"],
            page_size=filters["page_size"],
        )

    def list_role_templates(self, context: AdminContext) -> list[schema.AdminRoleTemplate]:
        self._bind_management_context(context)
        self.identity.require_permission(context, self.system_read_permission)
        return [
            schema.AdminRoleTemplate.model_validate(item) for item in role_templates(self.scope)
        ]
