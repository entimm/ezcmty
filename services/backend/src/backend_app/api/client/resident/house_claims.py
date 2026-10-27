from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Query, Response
from sqlalchemy.orm import Session

from backend_app.api.client.dependencies import ResidentContext as Context
from backend_app.api.client.dependencies import Store, client_responses
from backend_app.db.session import get_database_session
from backend_app.schemas import house_claims as schema
from backend_app.schemas.admin import Identifier
from backend_app.schemas.miniapp import IdempotencyKey
from backend_app.services.client.resident.house_claims import ResidentHouseClaimService


def service(db: Annotated[Session, Depends(get_database_session)]) -> ResidentHouseClaimService:
    return ResidentHouseClaimService(db)


Service = Annotated[ResidentHouseClaimService, Depends(service)]
Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=100)]
Sort = Literal["created_at", "-created_at"]


def create_resident_house_claim_router() -> APIRouter:
    router = APIRouter(prefix="/v1", tags=["miniapp"])
    ok = client_responses()

    @router.get(
        "/claimable-communities",
        operation_id="listClaimableCommunities",
        response_model=schema.ClaimableCommunityPage,
        responses=ok,
    )
    def communities(
        ctx: Context,
        svc: Service,
        name: Annotated[str | None, Query(max_length=160)] = None,
        page: Page = 1,
        page_size: PageSize = 20,
    ) -> schema.ClaimableCommunityPage:
        return svc.communities(ctx, name=name, page=page, page_size=page_size)

    @router.get(
        "/claimable-communities/{community_id}/space-nodes",
        operation_id="listClaimableSpaceNodes",
        response_model=schema.ClaimableSpaceNodePage,
        responses=ok,
    )
    def nodes(
        community_id: Identifier,
        ctx: Context,
        svc: Service,
        parent_id: Identifier | None = None,
        page: Page = 1,
        page_size: PageSize = 20,
    ) -> schema.ClaimableSpaceNodePage:
        return svc.nodes(ctx, community_id, parent_id=parent_id, page=page, page_size=page_size)

    @router.get(
        "/claimable-communities/{community_id}/houses",
        operation_id="listClaimableHouses",
        response_model=schema.ClaimableHousePage,
        responses=ok,
    )
    def houses(
        community_id: Identifier,
        space_node_id: Identifier,
        ctx: Context,
        svc: Service,
        room_no: Annotated[str | None, Query(max_length=32)] = None,
        page: Page = 1,
        page_size: PageSize = 20,
    ) -> schema.ClaimableHousePage:
        return svc.houses(
            ctx,
            community_id,
            space_node_id=space_node_id,
            room_no=room_no,
            page=page,
            page_size=page_size,
        )

    @router.get(
        "/claimable-communities/{community_id}/houses/{house_id}",
        operation_id="getClaimableHouse",
        response_model=schema.ClaimableHouse,
        responses=ok,
    )
    def house(
        community_id: Identifier, house_id: Identifier, ctx: Context, svc: Service
    ) -> schema.ClaimableHouse:
        return svc.house(ctx, community_id, house_id)

    @router.get(
        "/miniapp-users/me/house-claims",
        operation_id="listMyHouseClaims",
        response_model=schema.ResidentHouseClaimPage,
        responses=ok,
    )
    def claims(
        ctx: Context,
        svc: Service,
        status: schema.ClaimStatus | None = None,
        page: Page = 1,
        page_size: PageSize = 20,
        sort: Sort = "-created_at",
    ) -> schema.ResidentHouseClaimPage:
        return svc.claims(ctx, status=status, page=page, page_size=page_size, sort=sort)

    @router.post(
        "/miniapp-users/me/house-claims",
        operation_id="createHouseClaim",
        status_code=201,
        response_model=schema.ResidentHouseClaim,
        responses={
            **client_responses(201),
            200: {"headers": ok[200]["headers"], "model": schema.ResidentHouseClaim},
        },
    )
    def create(
        data: schema.HouseClaimCreate,
        ctx: Context,
        svc: Service,
        store: Store,
        response: Response,
        idempotency_key: Annotated[IdempotencyKey, Header(alias="Idempotency-Key")],
    ) -> schema.ResidentHouseClaim:
        store.limit("claim", ctx.user_id, store.settings.resident_claim_limit)
        claim, created = svc.create(ctx, data, idempotency_key)
        response.status_code = 201 if created else 200
        return claim

    @router.get(
        "/miniapp-users/me/house-claims/{claim_id}",
        operation_id="getMyHouseClaim",
        response_model=schema.ResidentHouseClaim,
        responses=ok,
    )
    def claim(claim_id: Identifier, ctx: Context, svc: Service) -> schema.ResidentHouseClaim:
        return svc.get_claim(ctx, claim_id)

    @router.post(
        "/miniapp-users/me/house-claims/{claim_id}/cancellations",
        operation_id="cancelHouseClaim",
        response_model=schema.ResidentHouseClaim,
        responses=ok,
    )
    def cancel(
        claim_id: Identifier, data: schema.ClaimCancellation, ctx: Context, svc: Service
    ) -> schema.ResidentHouseClaim:
        return svc.cancel(ctx, claim_id, data)

    @router.get(
        "/miniapp-users/me/house-bindings",
        operation_id="listMyHouseBindings",
        response_model=schema.ResidentHouseBindingPage,
        responses=ok,
    )
    def bindings(
        ctx: Context,
        svc: Service,
        status: schema.BindingStatus | None = None,
        page: Page = 1,
        page_size: PageSize = 20,
        sort: Sort = "-created_at",
    ) -> schema.ResidentHouseBindingPage:
        return svc.bindings(ctx, status=status, page=page, page_size=page_size, sort=sort)

    @router.get(
        "/miniapp-users/me/house-bindings/{binding_id}",
        operation_id="getMyHouseBinding",
        response_model=schema.ResidentHouseBinding,
        responses=ok,
    )
    def binding(binding_id: Identifier, ctx: Context, svc: Service) -> schema.ResidentHouseBinding:
        return svc.get_binding(ctx, binding_id)

    @router.post(
        "/miniapp-users/me/house-bindings/{binding_id}/releases",
        operation_id="releaseHouseBinding",
        response_model=schema.ResidentHouseBinding,
        responses=ok,
    )
    def release(
        binding_id: Identifier, data: schema.HouseRelease, ctx: Context, svc: Service
    ) -> schema.ResidentHouseBinding:
        return svc.release(ctx, binding_id, data)

    return router
