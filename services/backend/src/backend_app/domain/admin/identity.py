from backend_app.core.admin_security import dummy_password_hash, hash_password, verify_password
from backend_app.core.errors import AppError
from backend_app.domain.admin.audit import AdminAudit
from backend_app.domain.admin.permissions import permission_catalog
from backend_app.domain.admin.types import AdminAuthorization
from backend_app.models.admin import AdminAccount, AdminRole
from backend_app.repositories.admin import AdminRepository


class AdminIdentity:
    """Common identity rules; the application service owns use-case orchestration and commits."""

    def __init__(self, repo: AdminRepository):
        self.scope = repo.scope
        self.repo = repo
        self.audit = AdminAudit(repo)

    def bind_account(self, account: AdminAccount) -> None:
        if account.scope != self.scope:
            raise AppError("auth.forbidden")
        self.repo.property_company_id = account.property_company_id

    def validate_context(self, context: AdminAuthorization) -> None:
        if (
            context.scope != self.scope
            or context.property_company_id != self.repo.property_company_id
            or (self.scope == "property_admin" and context.property_company_id is None)
        ):
            raise AppError("auth.forbidden")

    def require_full_session(self, context: AdminAuthorization) -> None:
        self.validate_context(context)
        if context.must_change_password:
            raise AppError("auth.password_change_required")

    def require_permission(self, context: AdminAuthorization, permission: str) -> None:
        self.require_full_session(context)
        if permission not in context.permissions:
            raise AppError("auth.forbidden")

    def valid_credentials(self, account: AdminAccount | None, password: str) -> bool:
        valid = verify_password(
            account.password_hash if account else dummy_password_hash(), password
        )
        return account is not None and valid and account.enabled

    def session_account(self, account_id: str, version: int) -> AdminAccount:
        account = self.repo.identity(account_id)
        if account is None or not account.enabled or account.session_version != version:
            raise AppError("auth.unauthenticated")
        return account

    def authorization(self, account: AdminAccount) -> AdminAuthorization:
        self.bind_account(account)
        return AdminAuthorization(
            account_id=account.id,
            version=account.session_version,
            permissions=self.effective_permissions(account.id),
            must_change_password=account.must_change_password,
            scope=self.scope,
            property_company_id=account.property_company_id,
        )

    def record_login(self, account: AdminAccount | None, request_id: str, result: str) -> None:
        self.audit.record(
            actor=account,
            action="session.login",
            target_type="account",
            target_id=account.id if account else None,
            request_id=request_id,
            result=result,
        )

    def actor(self, context: AdminAuthorization) -> AdminAccount:
        self.validate_context(context)
        actor = self.account(context.account_id, lock=True)
        if not actor.enabled or actor.session_version != context.version:
            raise AppError("auth.unauthenticated")
        return actor

    def effective_permissions(self, account_id: str) -> list[str]:
        roles = [role for role in self.repo.account_roles(account_id) if role.enabled]
        catalog = permission_catalog(self.scope)
        if any(role.is_system and role.code == "super_admin" for role in roles):
            return sorted(item.code for item in catalog)
        allowed = {item.code for item in catalog if item.assignable}
        return sorted({code for role in roles for code in self.repo.permissions(role.id)} & allowed)

    def role_permissions(self, role: AdminRole) -> list[str]:
        return (
            sorted(item.code for item in permission_catalog(self.scope))
            if role.is_system
            else self.repo.permissions(role.id)
        )

    def account(self, account_id: str, *, lock: bool = False) -> AdminAccount:
        account = self.repo.account(account_id, lock=lock)
        if account is None:
            raise AppError("resource.not_found")
        return account

    def role(self, role_id: str, *, lock: bool = False) -> AdminRole:
        role = self.repo.role(role_id, lock=lock)
        if role is None:
            raise AppError("resource.not_found")
        return role

    def management_writer(self, context: AdminAuthorization) -> tuple[AdminAccount, AdminRole]:
        self.validate_context(context)
        # Serialize all authorization changes on one stable row per scope.
        system_role = self.repo.role_by_code("super_admin", lock=True)
        if system_role is None:
            raise AppError("auth.forbidden")
        actor = self.actor(context)
        if actor.must_change_password:
            raise AppError("auth.password_change_required")
        if not any(
            role.id == system_role.id and role.enabled
            for role in self.repo.account_roles(actor.id, lock=True)
        ):
            raise AppError("auth.forbidden")
        return actor, system_role

    def update_profile(self, actor: AdminAccount, display_name: str, request_id: str) -> None:
        actor.display_name = display_name
        self.audit.record(
            actor=actor,
            action="account.profile_update",
            target_type="account",
            target_id=actor.id,
            request_id=request_id,
            metadata={"changed_fields": ["display_name"]},
        )

    def change_password(
        self, actor: AdminAccount, current_password: str, new_password: str, request_id: str
    ) -> None:
        if not verify_password(actor.password_hash, current_password):
            raise AppError("auth.invalid_old_password")
        if current_password == new_password:
            raise AppError("resource.conflict", public_detail="新密码必须与当前密码不同")
        actor.password_hash = hash_password(new_password)
        actor.must_change_password = False
        actor.session_version += 1
        self.audit.record(
            actor=actor,
            action="account.password_change",
            target_type="account",
            target_id=actor.id,
            request_id=request_id,
        )
