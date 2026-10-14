from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from backend_app.core.admin_sessions import AdminSessionStore, StoredAdminSession
from backend_app.domain.admin.types import AdminAuthorization, AdminScope
from backend_app.schemas import admin as schema


@dataclass(frozen=True)
class AdminContext(AdminAuthorization):
    token: str
    stored: StoredAdminSession

    @classmethod
    def from_authorization(
        cls, authorization: AdminAuthorization, token: str, stored: StoredAdminSession
    ) -> AdminContext:
        return cls(
            account_id=authorization.account_id,
            version=authorization.version,
            permissions=authorization.permissions,
            must_change_password=authorization.must_change_password,
            scope=authorization.scope,
            property_company_id=authorization.property_company_id,
            token=token,
            stored=stored,
        )


class AdminAuthService(Protocol):
    @property
    def scope(self) -> AdminScope: ...

    def authenticate(self, store: AdminSessionStore, token: str | None) -> AdminContext: ...

    def login(
        self, data: schema.AdminLogin, store: AdminSessionStore, source_ip: str, request_id: str
    ) -> tuple[str, schema.AdminSession]: ...

    def get_current_session(self, context: AdminContext) -> schema.AdminSession: ...

    def get_profile(self, context: AdminContext) -> schema.AdminProfile: ...

    def update_profile(
        self, context: AdminContext, data: schema.ProfileUpdate, request_id: str
    ) -> schema.AdminProfile: ...

    def change_password(
        self, context: AdminContext, data: schema.PasswordChange, request_id: str
    ) -> None: ...
