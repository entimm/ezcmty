from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend_app.core.admin_security import (
    dummy_password_hash,
    hash_password,
    permission_catalog,
    verify_password,
)
from backend_app.core.admin_sessions import AdminSessionStore, StoredAdminSession
from backend_app.core.errors import AppError
from backend_app.models.admin import AdminAccount, AdminRole
from backend_app.repositories.admin import AdminRepository
from backend_app.schemas import admin as schema


@dataclass(frozen=True)
class AdminContext:
    account_id: str
    version: int
    permissions: list[str]
    must_change_password: bool
    token: str
    stored: StoredAdminSession


class AdminService:
    def __init__(self, db: Session, scope: schema.AdminScope):
        self.db = db
        self.scope = scope
        self.repo = AdminRepository(db, scope)

    def effective_permissions(self, account_id: str) -> list[str]:
        roles = [role for role in self.repo.account_roles(account_id) if role.enabled]
        catalog = permission_catalog(self.scope)
        if any(role.is_system and role.code == "super_admin" for role in roles):
            return sorted(item.code for item in catalog)
        allowed = {item.code for item in catalog if item.assignable}
        return sorted({code for role in roles for code in self.repo.permissions(role.id)} & allowed)

    def session_view(
        self, account: AdminAccount, stored: StoredAdminSession
    ) -> schema.AdminSession:
        return schema.AdminSession(
            scope=self.scope,
            subject_id=account.id,
            login_name=account.login_name,
            display_name=account.display_name,
            permissions=[]
            if account.must_change_password
            else self.effective_permissions(account.id),
            must_change_password=account.must_change_password,
            csrf_token=stored.csrf_token,
        )

    def authenticate(self, store: AdminSessionStore, token: str | None) -> AdminContext:
        if not token or len(token) > 128:
            raise AppError("auth.unauthenticated")
        record = store.read(self.scope, token)
        if record is None:
            raise AppError("auth.unauthenticated")
        account_id, stored = record
        account = self.repo.account(account_id)
        if (
            account is None
            or not account.enabled
            or account.session_version != stored.session_version
        ):
            raise AppError("auth.unauthenticated")
        store.touch(self.scope, token, stored)
        return AdminContext(
            account_id=account.id,
            version=account.session_version,
            permissions=self.effective_permissions(account.id),
            must_change_password=account.must_change_password,
            token=token,
            stored=stored,
        )

    def login(
        self, data: schema.AdminLogin, store: AdminSessionStore, source_ip: str, request_id: str
    ) -> tuple[str, schema.AdminSession]:
        store.limit_login(self.scope, data.login_name, source_ip)
        account = self.repo.account_by_login(data.login_name)
        valid = verify_password(
            account.password_hash if account else dummy_password_hash(), data.password
        )
        if account is None or not valid or not account.enabled:
            self.repo.audit(
                actor=account,
                action="session.login",
                target_type="account",
                target_id=account.id if account else None,
                result="failure",
                request_id=request_id,
            )
            self.db.commit()
            raise AppError("auth.invalid_credentials")
        token, stored = store.create(self.scope, account.id, account.session_version)
        view = self.session_view(account, stored)
        self.repo.audit(
            actor=account,
            action="session.login",
            target_type="account",
            target_id=account.id,
            request_id=request_id,
        )
        self.db.commit()
        return token, view

    def _account(self, account_id: str, *, lock: bool = False) -> AdminAccount:
        account = self.repo.account(account_id, lock=lock)
        if account is None:
            raise AppError("resource.not_found")
        return account

    def _role(self, role_id: str, *, lock: bool = False) -> AdminRole:
        role = self.repo.role(role_id, lock=lock)
        if role is None:
            raise AppError("resource.not_found")
        return role

    def _actor(self, context: AdminContext) -> AdminAccount:
        actor = self._account(context.account_id, lock=True)
        if not actor.enabled or actor.session_version != context.version:
            raise AppError("auth.unauthenticated")
        return actor

    def _writer(self, context: AdminContext) -> tuple[AdminAccount, AdminRole]:
        # Serialize all authorization changes on one stable row per scope.
        system_role = self.repo.role_by_code("super_admin", lock=True)
        if system_role is None:
            raise AppError("auth.forbidden")
        actor = self._actor(context)
        if actor.must_change_password:
            raise AppError("auth.password_change_required")
        if not any(
            role.id == system_role.id and role.enabled
            for role in self.repo.account_roles(actor.id, lock=True)
        ):
            raise AppError("auth.forbidden")
        return actor, system_role

    def account_view(self, account: AdminAccount) -> schema.AdminAccount:
        return schema.AdminAccount(
            id=account.id,
            scope=self.scope,
            login_name=account.login_name,
            display_name=account.display_name,
            enabled=account.enabled,
            must_change_password=account.must_change_password,
            created_at=account.created_at,
            roles=[
                schema.RoleSummary.model_validate(role)
                for role in self.repo.account_roles(account.id)
            ],
        )

    def role_view(self, role: AdminRole) -> schema.AdminRole:
        return schema.AdminRole(
            id=role.id,
            code=role.code,
            name=role.name,
            enabled=role.enabled,
            is_system=role.is_system,
            permissions=sorted(item.code for item in permission_catalog(self.scope))
            if role.is_system
            else self.repo.permissions(role.id),
        )

    def get_profile(self, context: AdminContext) -> schema.AdminProfile:
        return schema.AdminProfile.model_validate(self._account(context.account_id))

    def update_profile(
        self, context: AdminContext, data: schema.ProfileUpdate, request_id: str
    ) -> schema.AdminProfile:
        actor = self._actor(context)
        actor.display_name = data.display_name
        self.repo.audit(
            actor=actor,
            action="account.profile_update",
            target_type="account",
            target_id=actor.id,
            request_id=request_id,
            metadata={"changed_fields": ["display_name"]},
        )
        self.db.commit()
        return schema.AdminProfile.model_validate(actor)

    def change_password(
        self, context: AdminContext, data: schema.PasswordChange, request_id: str
    ) -> None:
        actor = self._actor(context)
        if not verify_password(actor.password_hash, data.current_password):
            raise AppError("auth.invalid_old_password")
        if data.current_password == data.new_password:
            raise AppError("resource.conflict", public_detail="新密码必须与当前密码不同")
        actor.password_hash = hash_password(data.new_password)
        actor.must_change_password = False
        actor.session_version += 1
        self.repo.audit(
            actor=actor,
            action="account.password_change",
            target_type="account",
            target_id=actor.id,
            request_id=request_id,
        )
        self.db.commit()

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
        actor, _ = self._writer(context)
        if self.repo.account_by_login(data.login_name):
            raise AppError("admin.duplicate_login")
        ids = self._validated_roles(data.role_ids)
        account = AdminAccount(
            scope=self.scope,
            login_name=data.login_name,
            display_name=data.display_name,
            password_hash=hash_password(data.password),
        )
        self.db.add(account)
        try:
            self.db.flush()
        except IntegrityError as exc:
            self.db.rollback()
            if self.repo.account_by_login(data.login_name):
                raise AppError("admin.duplicate_login") from exc
            raise
        self.repo.replace_roles(account.id, ids)
        self.repo.audit(
            actor=actor,
            action="account.create",
            target_type="account",
            target_id=account.id,
            request_id=request_id,
            metadata={"role_ids": sorted(ids)},
        )
        self.db.commit()
        return self.account_view(account)

    def update_account(
        self, context: AdminContext, account_id: str, data: schema.AccountUpdate, request_id: str
    ) -> schema.AdminAccount:
        actor, system_role = self._writer(context)
        account = self._account(account_id, lock=True)
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
        self.repo.audit(
            actor=actor,
            action="account.update",
            target_type="account",
            target_id=account.id,
            request_id=request_id,
            metadata={"changed_fields": changes},
        )
        self.db.commit()
        return self.account_view(account)

    def set_account_roles(
        self, context: AdminContext, account_id: str, data: schema.RoleSet, request_id: str
    ) -> schema.AdminAccount:
        actor, system_role = self._writer(context)
        account = self._account(account_id, lock=True)
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
        self.repo.audit(
            actor=actor,
            action="account.assign_roles",
            target_type="account",
            target_id=account.id,
            request_id=request_id,
            metadata={"role_ids": sorted(ids)},
        )
        self.db.commit()
        return self.account_view(account)

    def reset_password(
        self, context: AdminContext, account_id: str, data: schema.PasswordReset, request_id: str
    ) -> None:
        actor, _ = self._writer(context)
        account = self._account(account_id, lock=True)
        if actor.id == account.id:
            raise AppError("resource.conflict", public_detail="请通过个人中心修改本人密码")
        account.password_hash = hash_password(data.password)
        account.must_change_password = True
        account.session_version += 1
        self.repo.audit(
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
        actor, _ = self._writer(context)
        if self.repo.role_by_code(data.code):
            raise AppError("admin.duplicate_role")
        role = AdminRole(scope=self.scope, code=data.code, name=data.name)
        self.db.add(role)
        self.db.flush()
        self.repo.audit(
            actor=actor,
            action="role.create",
            target_type="role",
            target_id=role.id,
            request_id=request_id,
        )
        self.db.commit()
        return self.role_view(role)

    def update_role(
        self, context: AdminContext, role_id: str, data: schema.RoleUpdate, request_id: str
    ) -> schema.AdminRole:
        actor, _ = self._writer(context)
        role = self._role(role_id, lock=True)
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
        self.repo.audit(
            actor=actor,
            action="role.update",
            target_type="role",
            target_id=role.id,
            request_id=request_id,
            metadata={"changed_fields": changes},
        )
        self.db.commit()
        return self.role_view(role)

    def set_role_permissions(
        self, context: AdminContext, role_id: str, data: schema.PermissionSet, request_id: str
    ) -> schema.AdminRole:
        actor, _ = self._writer(context)
        role = self._role(role_id, lock=True)
        if role.is_system:
            raise AppError("admin.system_role_readonly")
        codes = set(data.permissions)
        allowed = {item.code for item in permission_catalog(self.scope) if item.assignable}
        if not codes <= allowed:
            raise AppError("admin.invalid_permission")
        if codes != set(self.repo.permissions(role.id, lock=True)):
            self.repo.replace_permissions(role.id, codes)
            self.repo.invalidate_role_accounts(role.id)
        self.repo.audit(
            actor=actor,
            action="role.assign_permissions",
            target_type="role",
            target_id=role.id,
            request_id=request_id,
            metadata={"permissions": sorted(codes)},
        )
        self.db.commit()
        return self.role_view(role)

    def list_accounts(self, **filters: Any) -> schema.AccountPage:
        items, total = self.repo.accounts(**filters)
        return schema.AccountPage(
            items=[self.account_view(item) for item in items],
            total=total,
            page=filters["page"],
            page_size=filters["page_size"],
        )

    def list_roles(self, **filters: Any) -> schema.RolePage:
        items, total = self.repo.roles(**filters)
        return schema.RolePage(
            items=[self.role_view(item) for item in items],
            total=total,
            page=filters["page"],
            page_size=filters["page_size"],
        )

    def list_audit(self, **filters: Any) -> schema.AuditPage:
        items, total = self.repo.audit_logs(**filters)
        return schema.AuditPage(
            items=[
                schema.AuditEntry(
                    id=item.id,
                    actor_id=item.actor_id,
                    actor_name=item.actor_name,
                    action=item.action,
                    target_type=item.target_type,
                    target_id=item.target_id,
                    result=cast(Any, item.result),
                    request_id=item.request_id,
                    created_at=item.created_at,
                    metadata=item.safe_metadata,
                )
                for item in items
            ],
            total=total,
            page=filters["page"],
            page_size=filters["page_size"],
        )

    def initialize_super_admin(self, login_name: str, display_name: str, password: str) -> None:
        data = schema.AccountCreate(
            login_name=login_name, display_name=display_name, password=password
        )
        if self.scope != "platform_admin":
            raise AppError("auth.forbidden")
        role = self.repo.role_by_code("super_admin", lock=True)
        if role is None:
            role = AdminRole(
                scope=self.scope,
                code="super_admin",
                name="超级管理员",
                enabled=True,
                is_system=True,
            )
            self.db.add(role)
            self.db.flush()
        if self.repo.active_super_accounts(role.id) or self.repo.account_by_login(data.login_name):
            raise AppError("resource.conflict", public_detail="已存在管理员，初始化不能覆盖")
        account = AdminAccount(
            scope=self.scope,
            login_name=data.login_name,
            display_name=data.display_name,
            password_hash=hash_password(data.password),
        )
        self.db.add(account)
        self.db.flush()
        self.repo.replace_roles(account.id, {role.id})
        self.repo.audit(
            actor=None,
            action="account.initialize",
            target_type="account",
            target_id=account.id,
            request_id="bootstrap",
        )
        self.db.commit()
