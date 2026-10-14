from sqlalchemy.orm import Session

from backend_app.core.admin_sessions import AdminSessionStore, StoredAdminSession
from backend_app.core.errors import AppError
from backend_app.domain.admin.identity import AdminIdentity
from backend_app.models.admin import AdminAccount
from backend_app.repositories.admin import AdminRepository
from backend_app.repositories.property import PropertyRepository
from backend_app.schemas import admin as schema
from backend_app.schemas.mappers import admin as views
from backend_app.services.contracts.admin import AdminContext


class PropertyAdminService:
    scope: schema.AdminScope = "property_admin"

    def __init__(self, db: Session):
        self.db = db
        self.identity = AdminIdentity(AdminRepository(db, self.scope))
        self.companies = PropertyRepository(db)

    def authenticate(self, store: AdminSessionStore, token: str | None) -> AdminContext:
        if not token or len(token) > 128:
            raise AppError("auth.unauthenticated")
        record = store.read(self.scope, token)
        if record is None:
            raise AppError("auth.unauthenticated")
        account_id, stored = record
        account = self.identity.session_account(account_id, stored.session_version)
        company_id = account.property_company_id
        if company_id is None:
            raise AppError("auth.unauthenticated")
        company = self.companies.company(company_id)
        if company is None or not company.enabled:
            raise AppError("auth.unauthenticated")
        self.identity.bind_account(account)
        store.touch(self.scope, token, stored)
        return AdminContext.from_authorization(self.identity.authorization(account), token, stored)

    def login(
        self, data: schema.AdminLogin, store: AdminSessionStore, source_ip: str, request_id: str
    ) -> tuple[str, schema.AdminSession]:
        store.limit_login(self.scope, data.login_name, source_ip)
        account = self.identity.repo.identity_by_login(data.login_name)
        company_enabled = False
        if account is not None and account.property_company_id is not None:
            # Coordinate with platform company/account changes and reload credentials
            # after any wait for their company -> account locks.
            company = self.companies.company(account.property_company_id, lock=True)
            self.identity.bind_account(account)
            account = self.identity.repo.account(account.id, lock=True)
            company_enabled = company is not None and company.enabled
        valid = self.identity.valid_credentials(account, data.password)
        if not valid or account is None or not company_enabled:
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

    def _actor(self, context: AdminContext) -> AdminAccount:
        self.identity.validate_context(context)
        company_id = context.property_company_id
        if company_id is None:
            raise AppError("auth.forbidden")
        company = self.companies.company(company_id, lock=True)
        if company is None or not company.enabled:
            raise AppError("auth.unauthenticated")
        return self.identity.actor(context)

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
        actor = self._actor(context)
        self.identity.update_profile(actor, data.display_name, request_id)
        self.db.commit()
        return views.profile_view(actor)

    def change_password(
        self, context: AdminContext, data: schema.PasswordChange, request_id: str
    ) -> None:
        actor = self._actor(context)
        self.identity.change_password(actor, data.current_password, data.new_password, request_id)
        self.db.commit()
