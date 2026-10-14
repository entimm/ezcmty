import secrets
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Query, Request, Response, Security
from fastapi.params import Depends as DependsParameter
from fastapi.security import APIKeyCookie
from sqlalchemy.orm import Session

from backend_app.core.admin_security import permission_catalog
from backend_app.core.admin_sessions import AdminSessionStore
from backend_app.core.config import get_settings
from backend_app.core.errors import AppError
from backend_app.core.openapi import get_problem_responses, get_request_id_headers
from backend_app.core.redis import get_redis
from backend_app.db.session import get_database_session
from backend_app.schemas import admin as schema
from backend_app.services.admin import AdminContext, AdminService

_cookie = APIKeyCookie(name="admin_session", scheme_name="AdminSession", auto_error=False)


def get_admin_session_store() -> AdminSessionStore:
    return AdminSessionStore(get_redis(), get_settings())


def create_admin_router(scope: schema.AdminScope) -> APIRouter:
    router = APIRouter(tags=["admin"])
    common_errors = get_problem_responses(401, 403, 404, 409, 422, 500, 503)
    session_headers = {**get_request_id_headers(), "Cache-Control": {"schema": {"type": "string"}}}
    cookie_headers = {**session_headers, "Set-Cookie": {"schema": {"type": "string"}}}

    def service(db: Annotated[Session, Depends(get_database_session)]) -> AdminService:
        return AdminService(db, scope)

    Service = Annotated[AdminService, Depends(service)]
    Store = Annotated[AdminSessionStore, Depends(get_admin_session_store)]

    def authenticate(
        svc: Service, store: Store, token: Annotated[str | None, Security(_cookie)]
    ) -> AdminContext:
        return svc.authenticate(store, token)

    Context = Annotated[AdminContext, Depends(authenticate)]

    def full_session(ctx: Context) -> AdminContext:
        if ctx.must_change_password:
            raise AppError("auth.password_change_required")
        return ctx

    FullContext = Annotated[AdminContext, Depends(full_session)]

    def permission(code: str) -> DependsParameter:
        def check(ctx: FullContext) -> AdminContext:
            if code not in ctx.permissions:
                raise AppError("auth.forbidden")
            return ctx

        return DependsParameter(check)

    def check_origin(origin: Annotated[str | None, Header(alias="Origin")] = None) -> None:
        if origin not in get_settings().admin_trusted_origins:
            raise AppError("auth.csrf_failed")

    def check_write(
        ctx: Context,
        x_csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
        _origin: Annotated[None, Depends(check_origin)] = None,
    ) -> None:
        if not x_csrf_token or not secrets.compare_digest(x_csrf_token, ctx.stored.csrf_token):
            raise AppError("auth.csrf_failed")

    def cookie_path() -> str:
        settings = get_settings()
        return (
            settings.platform_admin_cookie_path
            if scope == "platform_admin"
            else settings.property_admin_cookie_path
        )

    def clear_cookie(response: Response) -> None:
        response.delete_cookie(
            "admin_session",
            path=cookie_path(),
            httponly=True,
            secure=get_settings().env in {"production", "staging"},
            samesite="lax",
        )
        response.headers["Cache-Control"] = "no-store"

    @router.post(
        "/v1/admin-sessions",
        response_model=schema.AdminSession,
        status_code=201,
        operation_id="createAdminSession",
        dependencies=[Depends(check_origin)],
        responses={
            **get_problem_responses(401, 403, 422, 429, 500, 503),
            201: {"headers": cookie_headers},
        },
    )
    def login(
        data: schema.AdminLogin, request: Request, response: Response, svc: Service, store: Store
    ) -> schema.AdminSession:
        token, view = svc.login(
            data,
            store,
            request.client.host if request.client else "unknown",
            request.state.request_id,
        )
        response.set_cookie(
            "admin_session",
            token,
            path=cookie_path(),
            httponly=True,
            secure=get_settings().env in {"production", "staging"},
            samesite="lax",
            max_age=get_settings().admin_session_absolute_seconds,
        )
        response.headers["Cache-Control"] = "no-store"
        return view

    @router.get(
        "/v1/admin-sessions/current",
        response_model=schema.AdminSession,
        operation_id="getCurrentAdminSession",
        responses={**common_errors, 200: {"headers": session_headers}},
    )
    def get_current(ctx: Context, svc: Service, response: Response) -> schema.AdminSession:
        response.headers["Cache-Control"] = "no-store"
        return svc.session_view(svc._account(ctx.account_id), ctx.stored)

    @router.delete(
        "/v1/admin-sessions/current",
        status_code=204,
        operation_id="deleteCurrentAdminSession",
        dependencies=[Depends(check_write)],
        responses={**common_errors, 204: {"headers": cookie_headers}},
    )
    def logout(ctx: Context, store: Store, response: Response) -> None:
        store.delete(scope, ctx.token)
        clear_cookie(response)

    @router.get(
        "/v1/admin-accounts/me",
        response_model=schema.AdminProfile,
        operation_id="getOwnProfile",
        responses={**common_errors, 200: {"headers": get_request_id_headers()}},
    )
    def get_profile(ctx: FullContext, svc: Service) -> schema.AdminProfile:
        return svc.get_profile(ctx)

    @router.patch(
        "/v1/admin-accounts/me",
        response_model=schema.AdminProfile,
        operation_id="updateOwnProfile",
        dependencies=[Depends(check_write)],
        responses={**common_errors, 200: {"headers": get_request_id_headers()}},
    )
    def update_profile(
        data: schema.ProfileUpdate, request: Request, ctx: FullContext, svc: Service
    ) -> schema.AdminProfile:
        return svc.update_profile(ctx, data, request.state.request_id)

    @router.post(
        "/v1/admin-accounts/me/password-changes",
        status_code=204,
        operation_id="changeOwnPassword",
        dependencies=[Depends(check_write)],
        responses={**common_errors, 204: {"headers": cookie_headers}},
    )
    def change_password(
        data: schema.PasswordChange,
        request: Request,
        response: Response,
        ctx: Context,
        svc: Service,
        store: Store,
    ) -> None:
        svc.change_password(ctx, data, request.state.request_id)
        store.delete(scope, ctx.token)
        clear_cookie(response)

    @router.get(
        "/v1/admin-accounts",
        response_model=schema.AccountPage,
        operation_id="listAdminAccounts",
        dependencies=[permission("admin.account.read")],
        responses={**common_errors, 200: {"headers": get_request_id_headers()}},
    )
    def list_accounts(
        svc: Service,
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 20,
        login_name: Annotated[str | None, Query(max_length=64)] = None,
        enabled: bool | None = None,
        sort: Literal["created_at", "-created_at", "login_name", "-login_name"] = "-created_at",
    ) -> schema.AccountPage:
        return svc.list_accounts(
            page=page, page_size=page_size, login_name=login_name, enabled=enabled, sort=sort
        )

    @router.post(
        "/v1/admin-accounts",
        response_model=schema.AdminAccount,
        status_code=201,
        operation_id="createAdminAccount",
        dependencies=[Depends(check_write)],
        responses={**common_errors, 201: {"headers": get_request_id_headers()}},
    )
    def create_account(
        data: schema.AccountCreate,
        request: Request,
        svc: Service,
        ctx: Annotated[AdminContext, permission("admin.account.create")],
    ) -> schema.AdminAccount:
        return svc.create_account(ctx, data, request.state.request_id)

    @router.get(
        "/v1/admin-accounts/{account_id}",
        response_model=schema.AdminAccount,
        operation_id="getAdminAccount",
        dependencies=[permission("admin.account.read")],
        responses={**common_errors, 200: {"headers": get_request_id_headers()}},
    )
    def get_account(account_id: schema.Identifier, svc: Service) -> schema.AdminAccount:
        return svc.account_view(svc._account(account_id))

    @router.patch(
        "/v1/admin-accounts/{account_id}",
        response_model=schema.AdminAccount,
        operation_id="updateAdminAccount",
        dependencies=[Depends(check_write)],
        responses={**common_errors, 200: {"headers": get_request_id_headers()}},
    )
    def update_account(
        account_id: schema.Identifier,
        data: schema.AccountUpdate,
        request: Request,
        svc: Service,
        ctx: Annotated[AdminContext, permission("admin.account.update")],
    ) -> schema.AdminAccount:
        return svc.update_account(ctx, account_id, data, request.state.request_id)

    @router.post(
        "/v1/admin-accounts/{account_id}/password-resets",
        status_code=204,
        operation_id="resetAdminPassword",
        dependencies=[Depends(check_write)],
        responses={**common_errors, 204: {"headers": get_request_id_headers()}},
    )
    def reset_password(
        account_id: schema.Identifier,
        data: schema.PasswordReset,
        request: Request,
        svc: Service,
        ctx: Annotated[AdminContext, permission("admin.account.reset_password")],
    ) -> None:
        svc.reset_password(ctx, account_id, data, request.state.request_id)

    @router.put(
        "/v1/admin-accounts/{account_id}/roles",
        response_model=schema.AdminAccount,
        operation_id="setAdminAccountRoles",
        dependencies=[Depends(check_write)],
        responses={**common_errors, 200: {"headers": get_request_id_headers()}},
    )
    def set_account_roles(
        account_id: schema.Identifier,
        data: schema.RoleSet,
        request: Request,
        svc: Service,
        ctx: Annotated[AdminContext, permission("admin.account.assign_roles")],
    ) -> schema.AdminAccount:
        return svc.set_account_roles(ctx, account_id, data, request.state.request_id)

    @router.get(
        "/v1/admin-roles",
        response_model=schema.RolePage,
        operation_id="listAdminRoles",
        dependencies=[permission("admin.role.read")],
        responses={**common_errors, 200: {"headers": get_request_id_headers()}},
    )
    def list_roles(
        svc: Service,
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 20,
        name: Annotated[str | None, Query(max_length=80)] = None,
        enabled: bool | None = None,
        sort: Literal["code", "-code", "name", "-name"] = "code",
    ) -> schema.RolePage:
        return svc.list_roles(page=page, page_size=page_size, name=name, enabled=enabled, sort=sort)

    @router.post(
        "/v1/admin-roles",
        response_model=schema.AdminRole,
        status_code=201,
        operation_id="createAdminRole",
        dependencies=[Depends(check_write)],
        responses={**common_errors, 201: {"headers": get_request_id_headers()}},
    )
    def create_role(
        data: schema.RoleCreate,
        request: Request,
        svc: Service,
        ctx: Annotated[AdminContext, permission("admin.role.create")],
    ) -> schema.AdminRole:
        return svc.create_role(ctx, data, request.state.request_id)

    @router.get(
        "/v1/admin-roles/{role_id}",
        response_model=schema.AdminRole,
        operation_id="getAdminRole",
        dependencies=[permission("admin.role.read")],
        responses={**common_errors, 200: {"headers": get_request_id_headers()}},
    )
    def get_role(role_id: schema.Identifier, svc: Service) -> schema.AdminRole:
        return svc.role_view(svc._role(role_id))

    @router.patch(
        "/v1/admin-roles/{role_id}",
        response_model=schema.AdminRole,
        operation_id="updateAdminRole",
        dependencies=[Depends(check_write)],
        responses={**common_errors, 200: {"headers": get_request_id_headers()}},
    )
    def update_role(
        role_id: schema.Identifier,
        data: schema.RoleUpdate,
        request: Request,
        svc: Service,
        ctx: Annotated[AdminContext, permission("admin.role.update")],
    ) -> schema.AdminRole:
        return svc.update_role(ctx, role_id, data, request.state.request_id)

    @router.put(
        "/v1/admin-roles/{role_id}/permissions",
        response_model=schema.AdminRole,
        operation_id="setAdminRolePermissions",
        dependencies=[Depends(check_write)],
        responses={**common_errors, 200: {"headers": get_request_id_headers()}},
    )
    def set_permissions(
        role_id: schema.Identifier,
        data: schema.PermissionSet,
        request: Request,
        svc: Service,
        ctx: Annotated[AdminContext, permission("admin.role.assign_permissions")],
    ) -> schema.AdminRole:
        return svc.set_role_permissions(ctx, role_id, data, request.state.request_id)

    @router.get(
        "/v1/admin-permissions",
        response_model=list[schema.AdminPermission],
        operation_id="listAdminPermissions",
        dependencies=[permission("admin.role.read")],
        responses={**common_errors, 200: {"headers": get_request_id_headers()}},
    )
    def get_permissions() -> list[schema.AdminPermission]:
        return permission_catalog(scope)

    @router.get(
        "/v1/admin-audit-logs",
        response_model=schema.AuditPage,
        operation_id="listAdminAuditLogs",
        dependencies=[permission("admin.audit.read")],
        responses={
            **common_errors,
            **get_problem_responses(400),
            200: {"headers": get_request_id_headers()},
        },
    )
    def list_audit(
        svc: Service,
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 20,
        from_time: datetime | None = None,
        to_time: datetime | None = None,
        action: Annotated[str | None, Query(max_length=64)] = None,
        result: Literal["success", "failure"] | None = None,
        request_id: Annotated[str | None, Query(max_length=64)] = None,
        sort: Literal["created_at", "-created_at"] = "-created_at",
    ) -> schema.AuditPage:
        for value in (from_time, to_time):
            if value is not None and value.tzinfo is None:
                raise AppError("request.bad_request", public_detail="时间必须包含时区")
        if from_time and to_time and from_time > to_time:
            raise AppError("request.bad_request", public_detail="时间范围无效")
        return svc.list_audit(
            page=page,
            page_size=page_size,
            from_time=from_time.astimezone(UTC).replace(tzinfo=None) if from_time else None,
            to_time=to_time.astimezone(UTC).replace(tzinfo=None) if to_time else None,
            action=action,
            result=result,
            request_id=request_id,
            sort=sort,
        )

    if scope == "platform_admin":
        from backend_app.api.platform_admin.property import create_property_router

        platform = APIRouter()
        platform.include_router(router)
        platform.include_router(create_property_router(permission, check_write))
        return platform
    return router
