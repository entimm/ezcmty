from collections.abc import Callable
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.params import Depends as DependsParameter
from sqlalchemy.orm import Session

from backend_app.core.openapi import get_problem_responses, get_request_id_headers
from backend_app.db.session import get_database_session
from backend_app.schemas import admin as admin_schema
from backend_app.schemas import property as schema
from backend_app.schemas.admin import Identifier
from backend_app.services.admin import AdminContext
from backend_app.services.property import PropertyOnboardingService


def create_property_router(
    permission: Callable[[str], DependsParameter],
    check_write: Callable[..., None],
) -> APIRouter:
    router = APIRouter(tags=["property"])
    errors = get_problem_responses(401, 403, 404, 409, 422, 500, 503)
    ok = {**errors, 200: {"headers": get_request_id_headers()}}
    created = {**errors, 201: {"headers": get_request_id_headers()}}

    def service(db: Annotated[Session, Depends(get_database_session)]) -> PropertyOnboardingService:
        return PropertyOnboardingService(db)

    Service = Annotated[PropertyOnboardingService, Depends(service)]

    @router.get(
        "/v1/property-companies",
        response_model=schema.CompanyPage,
        operation_id="listPropertyCompanies",
        dependencies=[permission("property.company.read")],
        responses=ok,
    )
    def list_companies(
        svc: Service,
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 20,
        name: Annotated[str | None, Query(max_length=160)] = None,
        code: Annotated[str | None, Query(max_length=64)] = None,
        enabled: bool | None = None,
        sort: Literal["created_at", "-created_at"] = "-created_at",
    ) -> schema.CompanyPage:
        return svc.list_companies(
            page=page, page_size=page_size, name=name, code=code, enabled=enabled, sort=sort
        )

    @router.post(
        "/v1/property-companies",
        response_model=schema.PropertyCompany,
        status_code=201,
        operation_id="createPropertyCompany",
        dependencies=[Depends(check_write)],
        responses=created,
    )
    def create_company(
        data: schema.CompanyCreate,
        request: Request,
        svc: Service,
        ctx: Annotated[AdminContext, permission("property.company.create")],
    ) -> schema.PropertyCompany:
        return svc.create_company(ctx, data, request.state.request_id)

    @router.get(
        "/v1/property-companies/{company_id}",
        response_model=schema.PropertyCompany,
        operation_id="getPropertyCompany",
        dependencies=[permission("property.company.read")],
        responses=ok,
    )
    def get_company(company_id: Identifier, svc: Service) -> schema.PropertyCompany:
        return svc.get_company(company_id)

    @router.patch(
        "/v1/property-companies/{company_id}",
        response_model=schema.PropertyCompany,
        operation_id="updatePropertyCompany",
        dependencies=[Depends(check_write)],
        responses=ok,
    )
    def update_company(
        company_id: Identifier,
        data: schema.CompanyUpdate,
        request: Request,
        svc: Service,
        ctx: Annotated[AdminContext, permission("property.company.update")],
    ) -> schema.PropertyCompany:
        return svc.update_company(ctx, company_id, data, request.state.request_id)

    @router.get(
        "/v1/communities",
        response_model=schema.CommunityPage,
        operation_id="listCommunities",
        dependencies=[permission("property.community.read")],
        responses=ok,
    )
    def list_communities(
        svc: Service,
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 20,
        name: Annotated[str | None, Query(max_length=160)] = None,
        code: Annotated[str | None, Query(max_length=64)] = None,
        property_company_id: Identifier | None = None,
        enabled: bool | None = None,
        sort: Literal["created_at", "-created_at"] = "-created_at",
    ) -> schema.CommunityPage:
        return svc.list_communities(
            page=page,
            page_size=page_size,
            name=name,
            code=code,
            property_company_id=property_company_id,
            enabled=enabled,
            sort=sort,
        )

    @router.post(
        "/v1/communities",
        response_model=schema.Community,
        status_code=201,
        operation_id="createCommunity",
        dependencies=[Depends(check_write)],
        responses=created,
    )
    def create_community(
        data: schema.CommunityCreate,
        request: Request,
        svc: Service,
        ctx: Annotated[AdminContext, permission("property.community.create")],
    ) -> schema.Community:
        return svc.create_community(ctx, data, request.state.request_id)

    @router.get(
        "/v1/communities/{community_id}",
        response_model=schema.Community,
        operation_id="getCommunity",
        dependencies=[permission("property.community.read")],
        responses=ok,
    )
    def get_community(community_id: Identifier, svc: Service) -> schema.Community:
        return svc.get_community(community_id)

    @router.patch(
        "/v1/communities/{community_id}",
        response_model=schema.Community,
        operation_id="updateCommunity",
        dependencies=[Depends(check_write)],
        responses=ok,
    )
    def update_community(
        community_id: Identifier,
        data: schema.CommunityUpdate,
        request: Request,
        svc: Service,
        ctx: Annotated[AdminContext, permission("property.community.update")],
    ) -> schema.Community:
        return svc.update_community(ctx, community_id, data, request.state.request_id)

    @router.get(
        "/v1/property-companies/{company_id}/admin-accounts",
        response_model=schema.PropertyAdminPage,
        operation_id="listPropertyAdminAccounts",
        dependencies=[permission("property.admin.read")],
        responses=ok,
    )
    def list_admins(
        company_id: Identifier,
        svc: Service,
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 20,
        login_name: Annotated[str | None, Query(max_length=64)] = None,
        enabled: bool | None = None,
        sort: Literal["created_at", "-created_at"] = "-created_at",
    ) -> schema.PropertyAdminPage:
        return svc.list_admins(
            company_id,
            page=page,
            page_size=page_size,
            login_name=login_name,
            enabled=enabled,
            sort=sort,
        )

    @router.post(
        "/v1/property-companies/{company_id}/admin-accounts",
        response_model=schema.PropertyAdminAccount,
        status_code=201,
        operation_id="createPropertyAdminAccount",
        dependencies=[Depends(check_write)],
        responses=created,
    )
    def create_admin(
        company_id: Identifier,
        data: schema.PropertyAdminCreate,
        request: Request,
        svc: Service,
        ctx: Annotated[AdminContext, permission("property.admin.create")],
    ) -> schema.PropertyAdminAccount:
        return svc.create_admin(ctx, company_id, data, request.state.request_id)

    @router.get(
        "/v1/property-companies/{company_id}/admin-accounts/{account_id}",
        response_model=schema.PropertyAdminAccount,
        operation_id="getPropertyAdminAccount",
        dependencies=[permission("property.admin.read")],
        responses=ok,
    )
    def get_admin(
        company_id: Identifier, account_id: Identifier, svc: Service
    ) -> schema.PropertyAdminAccount:
        return svc.get_admin(company_id, account_id)

    @router.patch(
        "/v1/property-companies/{company_id}/admin-accounts/{account_id}",
        response_model=schema.PropertyAdminAccount,
        operation_id="updatePropertyAdminAccount",
        dependencies=[Depends(check_write)],
        responses=ok,
    )
    def update_admin(
        company_id: Identifier,
        account_id: Identifier,
        data: admin_schema.AccountUpdate,
        request: Request,
        svc: Service,
        ctx: Annotated[AdminContext, permission("property.admin.update")],
    ) -> schema.PropertyAdminAccount:
        return svc.update_admin(ctx, company_id, account_id, data, request.state.request_id)

    @router.post(
        "/v1/property-companies/{company_id}/admin-accounts/{account_id}/password-resets",
        status_code=204,
        operation_id="resetPropertyAdminPassword",
        dependencies=[Depends(check_write)],
        responses={**errors, 204: {"headers": get_request_id_headers()}},
    )
    def reset_admin_password(
        company_id: Identifier,
        account_id: Identifier,
        data: admin_schema.PasswordReset,
        request: Request,
        svc: Service,
        ctx: Annotated[AdminContext, permission("property.admin.reset_password")],
    ) -> None:
        svc.reset_admin_password(ctx, company_id, account_id, data, request.state.request_id)

    return router
