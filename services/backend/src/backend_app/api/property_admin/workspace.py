from collections.abc import Callable
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.params import Depends as DependsParameter
from sqlalchemy.orm import Session

from backend_app.core.openapi import get_problem_responses, get_request_id_headers
from backend_app.db.session import get_database_session
from backend_app.schemas import property as schema
from backend_app.schemas.admin import Identifier
from backend_app.services.admin import AdminContext
from backend_app.services.property_workspace import PropertyWorkspaceService


def create_property_workspace_router(permission: Callable[[str], DependsParameter]) -> APIRouter:
    router = APIRouter(tags=["property"])
    responses = {
        **get_problem_responses(401, 403, 404, 409, 422, 500, 503),
        200: {"headers": get_request_id_headers()},
    }

    def service(db: Annotated[Session, Depends(get_database_session)]) -> PropertyWorkspaceService:
        return PropertyWorkspaceService(db)

    Service = Annotated[PropertyWorkspaceService, Depends(service)]

    @router.get(
        "/v1/property-companies/current",
        response_model=schema.PropertyCompany,
        operation_id="getCurrentPropertyCompany",
        responses=responses,
    )
    def get_current_company(
        svc: Service, ctx: Annotated[AdminContext, permission("property.company.read")]
    ) -> schema.PropertyCompany:
        return svc.get_current_company(ctx)

    @router.get(
        "/v1/communities",
        response_model=schema.CommunityPage,
        operation_id="listCommunities",
        responses=responses,
    )
    def list_communities(
        svc: Service,
        ctx: Annotated[AdminContext, permission("property.community.read")],
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 20,
        name: Annotated[str | None, Query(max_length=160)] = None,
        code: Annotated[str | None, Query(max_length=64)] = None,
        property_company_id: Identifier | None = None,
        enabled: bool | None = None,
        sort: Literal["created_at", "-created_at"] = "-created_at",
    ) -> schema.CommunityPage:
        return svc.list_communities(
            ctx,
            page=page,
            page_size=page_size,
            name=name,
            code=code,
            property_company_id=property_company_id,
            enabled=enabled,
            sort=sort,
        )

    @router.get(
        "/v1/communities/{community_id}",
        response_model=schema.Community,
        operation_id="getCommunity",
        responses=responses,
    )
    def get_community(
        community_id: Identifier,
        svc: Service,
        ctx: Annotated[AdminContext, permission("property.community.read")],
    ) -> schema.Community:
        return svc.get_community(ctx, community_id)

    return router
