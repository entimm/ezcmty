from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.params import Depends as DependsParameter
from sqlalchemy.orm import Session

from backend_app.core.errors import AppError
from backend_app.core.openapi import get_problem_responses, get_request_id_headers
from backend_app.db.session import get_database_session
from backend_app.schemas import admin as schema
from backend_app.services.contracts.admin import AdminContext
from backend_app.services.platform_admin.admin import PlatformAdminService


def create_platform_management_router(
    permission: Callable[[str], DependsParameter], check_write: Callable[..., None]
) -> APIRouter:
    router = APIRouter(tags=["admin"])
    common_errors = get_problem_responses(401, 403, 404, 409, 422, 500, 503)

    def service(db: Annotated[Session, Depends(get_database_session)]) -> PlatformAdminService:
        return PlatformAdminService(db)

    Service = Annotated[PlatformAdminService, Depends(service)]

    @router.get(
        "/v1/admin-accounts",
        response_model=schema.AccountPage,
        operation_id="listAdminAccounts",
        responses={**common_errors, 200: {"headers": get_request_id_headers()}},
    )
    def list_accounts(
        svc: Service,
        ctx: Annotated[AdminContext, permission("admin.account.read")],
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 20,
        login_name: Annotated[str | None, Query(max_length=64)] = None,
        enabled: bool | None = None,
        sort: Literal["created_at", "-created_at", "login_name", "-login_name"] = "-created_at",
    ) -> schema.AccountPage:
        return svc.list_accounts(
            ctx, page=page, page_size=page_size, login_name=login_name, enabled=enabled, sort=sort
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
        responses={**common_errors, 200: {"headers": get_request_id_headers()}},
    )
    def get_account(
        account_id: schema.Identifier,
        svc: Service,
        ctx: Annotated[AdminContext, permission("admin.account.read")],
    ) -> schema.AdminAccount:
        return svc.get_account(ctx, account_id)

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
        responses={**common_errors, 200: {"headers": get_request_id_headers()}},
    )
    def list_roles(
        svc: Service,
        ctx: Annotated[AdminContext, permission("admin.role.read")],
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 20,
        name: Annotated[str | None, Query(max_length=80)] = None,
        enabled: bool | None = None,
        sort: Literal["code", "-code", "name", "-name"] = "code",
    ) -> schema.RolePage:
        return svc.list_roles(
            ctx, page=page, page_size=page_size, name=name, enabled=enabled, sort=sort
        )

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
        responses={**common_errors, 200: {"headers": get_request_id_headers()}},
    )
    def get_role(
        role_id: schema.Identifier,
        svc: Service,
        ctx: Annotated[AdminContext, permission("admin.role.read")],
    ) -> schema.AdminRole:
        return svc.get_role(ctx, role_id)

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
        responses={**common_errors, 200: {"headers": get_request_id_headers()}},
    )
    def get_permissions(
        svc: Service, ctx: Annotated[AdminContext, permission("admin.role.read")]
    ) -> list[schema.AdminPermission]:
        return svc.list_permissions(ctx)

    @router.get(
        "/v1/admin-audit-logs",
        response_model=schema.AuditPage,
        operation_id="listAdminAuditLogs",
        responses={
            **common_errors,
            **get_problem_responses(400),
            200: {"headers": get_request_id_headers()},
        },
    )
    def list_audit(
        svc: Service,
        ctx: Annotated[AdminContext, permission("admin.audit.read")],
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
            ctx,
            page=page,
            page_size=page_size,
            from_time=from_time.astimezone(UTC) if from_time else None,
            to_time=to_time.astimezone(UTC) if to_time else None,
            action=action,
            result=result,
            request_id=request_id,
            sort=sort,
        )

    return router
