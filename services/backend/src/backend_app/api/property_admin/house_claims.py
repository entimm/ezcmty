from collections.abc import Callable
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.params import Depends as DependsParameter
from pydantic import AwareDatetime
from sqlalchemy.orm import Session

from backend_app.core.openapi import get_problem_responses, get_request_id_headers
from backend_app.db.session import get_database_session
from backend_app.schemas import house_claims as schema
from backend_app.schemas.admin import Identifier
from backend_app.services.contracts.admin import AdminContext
from backend_app.services.property_admin.house_claims import PropertyHouseClaimService

Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=100)]
Sort = Literal["created_at", "-created_at"]


def create_property_house_claim_router(
    permission: Callable[[str], DependsParameter], check_write: Callable[..., None]
) -> APIRouter:
    router = APIRouter(prefix="/v1", tags=["miniapp"])
    ok = {
        **get_problem_responses(401, 403, 404, 409, 422, 500, 503),
        200: {"headers": get_request_id_headers()},
    }

    def service(db: Annotated[Session, Depends(get_database_session)]) -> PropertyHouseClaimService:
        return PropertyHouseClaimService(db)

    Service = Annotated[PropertyHouseClaimService, Depends(service)]

    @router.get(
        "/house-claims",
        operation_id="listPropertyHouseClaims",
        response_model=schema.PropertyHouseClaimPage,
        responses=ok,
    )
    def claims(
        svc: Service,
        ctx: Annotated[AdminContext, permission("property.house_claim.read")],
        status: schema.ClaimStatus | None = None,
        match_status: schema.MatchStatus | None = None,
        community_id: Identifier | None = None,
        house_id: Identifier | None = None,
        created_from: AwareDatetime | None = None,
        created_to: AwareDatetime | None = None,
        page: Page = 1,
        page_size: PageSize = 20,
        sort: Sort = "-created_at",
    ) -> schema.PropertyHouseClaimPage:
        return svc.claims(
            ctx,
            status=status,
            match_status=match_status,
            community_id=community_id,
            house_id=house_id,
            created_from=created_from,
            created_to=created_to,
            page=page,
            page_size=page_size,
            sort=sort,
        )

    @router.get(
        "/house-claims/{claim_id}",
        operation_id="getPropertyHouseClaim",
        response_model=schema.PropertyHouseClaim,
        responses=ok,
    )
    def claim(
        claim_id: Identifier,
        svc: Service,
        ctx: Annotated[AdminContext, permission("property.house_claim.read")],
    ) -> schema.PropertyHouseClaim:
        return svc.get_claim(ctx, claim_id)

    @router.post(
        "/house-claims/{claim_id}/reviews",
        operation_id="reviewHouseClaim",
        response_model=schema.PropertyHouseClaim,
        responses=ok,
        dependencies=[Depends(check_write)],
    )
    def review(
        claim_id: Identifier,
        data: schema.ClaimReview,
        request: Request,
        svc: Service,
        ctx: Annotated[AdminContext, permission("property.house_claim.review")],
    ) -> schema.PropertyHouseClaim:
        return svc.review(ctx, claim_id, data, request.state.request_id)

    @router.get(
        "/resident-house-bindings",
        operation_id="listPropertyHouseBindings",
        response_model=schema.PropertyHouseBindingPage,
        responses=ok,
    )
    def bindings(
        svc: Service,
        ctx: Annotated[AdminContext, permission("property.resident_house_binding.read")],
        status: schema.BindingStatus | None = None,
        community_id: Identifier | None = None,
        house_id: Identifier | None = None,
        created_from: AwareDatetime | None = None,
        created_to: AwareDatetime | None = None,
        page: Page = 1,
        page_size: PageSize = 20,
        sort: Sort = "-created_at",
    ) -> schema.PropertyHouseBindingPage:
        return svc.bindings(
            ctx,
            status=status,
            community_id=community_id,
            house_id=house_id,
            created_from=created_from,
            created_to=created_to,
            page=page,
            page_size=page_size,
            sort=sort,
        )

    @router.get(
        "/resident-house-bindings/{binding_id}",
        operation_id="getPropertyHouseBinding",
        response_model=schema.PropertyHouseBinding,
        responses=ok,
    )
    def binding(
        binding_id: Identifier,
        svc: Service,
        ctx: Annotated[AdminContext, permission("property.resident_house_binding.read")],
    ) -> schema.PropertyHouseBinding:
        return svc.get_binding(ctx, binding_id)

    @router.post(
        "/resident-house-bindings/{binding_id}/revocations",
        operation_id="revokeHouseBinding",
        response_model=schema.PropertyHouseBinding,
        responses=ok,
        dependencies=[Depends(check_write)],
    )
    def revoke(
        binding_id: Identifier,
        data: schema.HouseRevocation,
        request: Request,
        svc: Service,
        ctx: Annotated[AdminContext, permission("property.resident_house_binding.revoke")],
    ) -> schema.PropertyHouseBinding:
        return svc.revoke(ctx, binding_id, data, request.state.request_id)

    return router
