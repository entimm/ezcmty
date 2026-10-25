import secrets
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request, Response, Security
from fastapi.params import Depends as DependsParameter
from fastapi.security import APIKeyCookie
from sqlalchemy.orm import Session

from backend_app.core.admin_sessions import AdminSessionStore
from backend_app.core.config import get_settings
from backend_app.core.errors import AppError
from backend_app.core.openapi import get_problem_responses, get_request_id_headers
from backend_app.core.redis import get_redis
from backend_app.db.session import get_database_session
from backend_app.schemas import admin as schema
from backend_app.services.contracts.admin import AdminAuthService, AdminContext

_cookie = APIKeyCookie(name="admin_session", scheme_name="AdminSession", auto_error=False)


def get_admin_session_store() -> AdminSessionStore:
    return AdminSessionStore(get_redis(), get_settings())


@dataclass(frozen=True)
class AdminAuthRoutes:
    router: APIRouter
    permission: Callable[[str], DependsParameter]
    check_write: Callable[..., None]


def create_admin_auth_router(
    scope: schema.AdminScope, service_factory: Callable[[Session], AdminAuthService]
) -> AdminAuthRoutes:
    router = APIRouter(tags=["admin"])
    common_errors = get_problem_responses(401, 403, 404, 409, 422, 500, 503)
    session_headers = {**get_request_id_headers(), "Cache-Control": {"schema": {"type": "string"}}}
    cookie_headers = {**session_headers, "Set-Cookie": {"schema": {"type": "string"}}}

    def service(db: Annotated[Session, Depends(get_database_session)]) -> AdminAuthService:
        svc = service_factory(db)
        if svc.scope != scope:
            raise RuntimeError("Admin API and application service scopes must match")
        return svc

    Service = Annotated[AdminAuthService, Depends(service)]
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
            # Empty code binds a full session; the target service checks its business authority.
            if code and code not in ctx.permissions:
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
        return svc.get_current_session(ctx)

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

    return AdminAuthRoutes(router=router, permission=permission, check_write=check_write)
