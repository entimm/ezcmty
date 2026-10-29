"""Property-account authorization and audit adapter for shared business use cases."""

from typing import Any

from sqlalchemy.orm import Session

from backend_app.core.errors import AppError
from backend_app.domain.admin.identity import AdminIdentity
from backend_app.domain.admin.types import AdminAuthorization
from backend_app.repositories.admin import AdminRepository
from backend_app.repositories.property import PropertyRepository
from backend_app.services.property_business.context import BusinessActor, PropertyBusinessContext


class PropertyAccountAuthority:
    def __init__(self, db: Session, authorization: AdminAuthorization | None = None):
        self.db = db
        self.authorization = authorization

    def authorize(
        self,
        context: PropertyBusinessContext,
        actions: frozenset[str],
        *,
        lock: bool,
        shared: bool,
    ) -> BusinessActor:
        if context.source != "property_admin":
            raise AppError("auth.forbidden")
        auth = self.authorization
        if auth is not None and (
            auth.scope != "property_admin"
            or auth.property_company_id != context.company_id
            or auth.account_id != context.actor_id
        ):
            raise AppError("auth.forbidden")
        if auth is not None:
            if auth.must_change_password:
                raise AppError("auth.password_change_required")
            snapshot_permissions = frozenset(
                code.removeprefix("property.") for code in auth.permissions
            )
            if not actions <= snapshot_permissions:
                raise AppError("auth.forbidden")
            if not lock:
                # The HTTP authenticator already checked this request's account/company.
                # Names are only needed by writers, which always resolve the locked actor.
                return BusinessActor(auth.account_id, "", snapshot_permissions)
        company = PropertyRepository(self.db).company(context.company_id, lock=lock, shared=shared)
        if company is None or not company.enabled:
            raise AppError("auth.unauthenticated")
        repo = AdminRepository(self.db, "property_admin", context.company_id)
        actor = repo.account(context.actor_id, lock=lock, shared=shared)
        if (
            actor is None
            or not actor.enabled
            or (auth is not None and actor.session_version != auth.version)
        ):
            raise AppError("auth.unauthenticated")
        if actor.must_change_password:
            raise AppError("auth.password_change_required")
        permissions = frozenset(
            code.removeprefix("property.")
            for code in AdminIdentity(repo).effective_permissions(actor.id)
        )
        if auth is not None:
            if auth.must_change_password:
                raise AppError("auth.password_change_required")
            permissions &= frozenset(code.removeprefix("property.") for code in auth.permissions)
        if not actions <= permissions:
            raise AppError("auth.forbidden")
        return BusinessActor(actor.id, actor.display_name, permissions)

    def record(
        self,
        context: PropertyBusinessContext,
        actor: BusinessActor,
        *,
        action: str,
        target_type: str,
        target_id: str,
        request_id: str,
        metadata: dict[str, Any],
    ) -> None:
        if context.source != "property_admin" or actor.id != context.actor_id:
            raise AppError("auth.forbidden")
        identity = AdminIdentity(AdminRepository(self.db, "property_admin", context.company_id))
        account = identity.account(actor.id)
        identity.audit.record(
            actor=account,
            action=action,
            target_type=target_type,
            target_id=target_id,
            request_id=request_id,
            metadata=metadata,
        )


def property_business_context(db: Session, auth: AdminAuthorization) -> PropertyBusinessContext:
    if auth.scope != "property_admin" or auth.property_company_id is None:
        raise AppError("auth.forbidden")
    snapshot = AdminAuthorization(
        account_id=auth.account_id,
        version=auth.version,
        permissions=list(auth.permissions),
        must_change_password=auth.must_change_password,
        scope=auth.scope,
        property_company_id=auth.property_company_id,
    )
    return PropertyBusinessContext(
        auth.property_company_id,
        auth.account_id,
        auth.scope,
        PropertyAccountAuthority(db, snapshot),
    )


def property_task_context(db: Session, company_id: str, actor_id: str) -> PropertyBusinessContext:
    return PropertyBusinessContext(
        company_id, actor_id, "property_admin", PropertyAccountAuthority(db)
    )
