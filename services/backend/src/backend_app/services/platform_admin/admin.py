from sqlalchemy.orm import Session

from backend_app.core.admin_security import hash_password
from backend_app.core.admin_sessions import AdminSessionStore, StoredAdminSession
from backend_app.core.errors import AppError
from backend_app.models.admin import AdminAccount, AdminRole
from backend_app.schemas import admin as schema
from backend_app.schemas.mappers import admin as views
from backend_app.services.admin_management import AdminManagementService
from backend_app.services.contracts.admin import AdminContext


class PlatformAdminService(AdminManagementService):
    scope: schema.AdminScope = "platform_admin"

    def __init__(self, db: Session):
        super().__init__(db, self.scope)

    def authenticate(self, store: AdminSessionStore, token: str | None) -> AdminContext:
        if not token or len(token) > 128:
            raise AppError("auth.unauthenticated")
        record = store.read(self.scope, token)
        if record is None:
            raise AppError("auth.unauthenticated")
        account_id, stored = record
        account = self.identity.session_account(account_id, stored.session_version)
        if account.property_company_id is not None:
            raise AppError("auth.unauthenticated")
        self.identity.bind_account(account)
        store.touch(self.scope, token, stored)
        return AdminContext.from_authorization(self.identity.authorization(account), token, stored)

    def login(
        self, data: schema.AdminLogin, store: AdminSessionStore, source_ip: str, request_id: str
    ) -> tuple[str, schema.AdminSession]:
        store.limit_login(self.scope, data.login_name, source_ip)
        account = self.repo.identity_by_login(data.login_name)
        valid = self.identity.valid_credentials(account, data.password)
        if not valid or account is None or account.property_company_id is not None:
            self.identity.record_login(account, request_id, "failure")
            self.db.commit()
            raise AppError("auth.invalid_credentials")
        self.identity.bind_account(account)
        token, stored = store.create(self.scope, account.id, account.session_version)
        view = self._session_view(account, stored)
        self.identity.record_login(account, request_id, "success")
        self.db.commit()
        return token, view

    def _session_view(
        self, account: AdminAccount, stored: StoredAdminSession
    ) -> schema.AdminSession:
        permissions = (
            [] if account.must_change_password else self.identity.effective_permissions(account.id)
        )
        return views.session_view(
            account, scope=self.scope, permissions=permissions, csrf_token=stored.csrf_token
        )

    def get_current_session(self, context: AdminContext) -> schema.AdminSession:
        self.identity.validate_context(context)
        return self._session_view(self.identity.account(context.account_id), context.stored)

    def get_profile(self, context: AdminContext) -> schema.AdminProfile:
        self.identity.require_full_session(context)
        return views.profile_view(self.identity.account(context.account_id))

    def update_profile(
        self, context: AdminContext, data: schema.ProfileUpdate, request_id: str
    ) -> schema.AdminProfile:
        self.identity.require_full_session(context)
        actor = self.identity.actor(context)
        self.identity.update_profile(actor, data.display_name, request_id)
        self.db.commit()
        return views.profile_view(actor)

    def change_password(
        self, context: AdminContext, data: schema.PasswordChange, request_id: str
    ) -> None:
        actor = self.identity.actor(context)
        self.identity.change_password(actor, data.current_password, data.new_password, request_id)
        self.db.commit()

    def initialize_super_admin(self, login_name: str, display_name: str, password: str) -> None:
        data = schema.AccountCreate(
            login_name=login_name, display_name=display_name, password=password
        )
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
        self.identity.audit.record(
            actor=None,
            action="account.initialize",
            target_type="account",
            target_id=account.id,
            request_id="bootstrap",
        )
        self.db.commit()
