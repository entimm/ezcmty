from __future__ import annotations

from typing import Any

from backend_app.core.errors import AppError
from backend_app.domain.admin.permissions import permission_prefix
from backend_app.domain.admin.types import AdminAuthorization
from backend_app.models.admin import AdminAccount, AdminAuditLog
from backend_app.repositories.admin import AdminRepository


class AdminAudit:
    def __init__(self, repo: AdminRepository):
        self.repo = repo
        self.scope = repo.scope

    def record(
        self,
        *,
        actor: AdminAccount | None,
        action: str,
        target_type: str,
        target_id: str | None,
        request_id: str,
        result: str = "success",
        property_company_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        company_id = property_company_id
        if self.scope == "property_admin":
            if action == "session.login":
                company_id = actor.property_company_id if actor else None
            else:
                company_id = self.repo.property_company_id
            unknown_login = action == "session.login" and result == "failure" and actor is None
            if company_id is None and not unknown_login:
                raise AppError("auth.forbidden")
            if actor is not None and (
                actor.scope != self.scope or actor.property_company_id != company_id
            ):
                raise AppError("auth.forbidden")
            if property_company_id is not None and property_company_id != company_id:
                raise AppError("auth.forbidden")
        self.repo.audit(
            actor=actor,
            action=action,
            target_type=target_type,
            target_id=target_id,
            request_id=request_id,
            result=result,
            property_company_id=company_id,
            metadata=metadata,
        )

    def list_logs(
        self, context: AdminAuthorization, **filters: Any
    ) -> tuple[list[AdminAuditLog], int]:
        if (
            context.scope != self.scope
            or context.property_company_id != self.repo.property_company_id
            or (self.scope == "property_admin" and context.property_company_id is None)
        ):
            raise AppError("auth.forbidden")
        if context.must_change_password:
            raise AppError("auth.password_change_required")
        if f"{permission_prefix(self.scope)}.audit.read" not in context.permissions:
            raise AppError("auth.forbidden")
        return self.repo.audit_logs(**filters)
