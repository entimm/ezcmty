from collections.abc import Callable
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.params import Depends as DependsParameter
from sqlalchemy.orm import Session

from backend_app.core.openapi import get_problem_responses, get_request_id_headers
from backend_app.db.session import get_database_session
from backend_app.schemas import housing as schema
from backend_app.schemas.admin import Identifier
from backend_app.services.contracts.admin import AdminContext
from backend_app.services.property_admin.housing import PropertyHousingService


def create_property_housing_router(
    permission: Callable[[str], DependsParameter], check_write: Callable[..., None]
) -> APIRouter:
    router = APIRouter(tags=["housing"], prefix="/v1/communities/{community_id}")
    errors = get_problem_responses(401, 403, 404, 409, 422, 500, 503)
    ok = {**errors, 200: {"headers": get_request_id_headers()}}
    created = {**errors, 201: {"headers": get_request_id_headers()}}

    def service(db: Annotated[Session, Depends(get_database_session)]) -> PropertyHousingService:
        return PropertyHousingService(db)

    Service = Annotated[PropertyHousingService, Depends(service)]

    @router.get(
        "/house-options",
        response_model=schema.HouseOptionPage,
        operation_id="listHouseOptions",
        responses=ok,
    )
    def house_options(
        community_id: Identifier,
        svc: Service,
        ctx: Annotated[AdminContext, permission("")],
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 20,
        room_no: Annotated[str | None, Query(max_length=32)] = None,
        house_id: Identifier | None = None,
    ) -> schema.HouseOptionPage:
        return svc.house_options(
            ctx, community_id, page=page, page_size=page_size, room_no=room_no, house_id=house_id
        )

    @router.get(
        "/space-nodes",
        response_model=schema.SpaceNodePage,
        operation_id="listSpaceNodes",
        responses=ok,
    )
    def list_nodes(
        community_id: Identifier,
        svc: Service,
        ctx: Annotated[AdminContext, permission("property.housing.read")],
        parent_id: Identifier | None = None,
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    ) -> schema.SpaceNodePage:
        return svc.list_nodes(
            ctx, community_id, parent_id=parent_id, page=page, page_size=page_size
        )

    @router.post(
        "/space-nodes",
        response_model=schema.SpaceNode,
        status_code=201,
        operation_id="createSpaceNode",
        dependencies=[Depends(check_write)],
        responses=created,
    )
    def create_node(
        community_id: Identifier,
        data: schema.SpaceNodeCreate,
        request: Request,
        svc: Service,
        ctx: Annotated[AdminContext, permission("property.housing.manage")],
    ) -> schema.SpaceNode:
        return svc.create_node(ctx, community_id, data, request.state.request_id)

    @router.get(
        "/space-nodes/{node_id}",
        response_model=schema.SpaceNode,
        operation_id="getSpaceNode",
        responses=ok,
    )
    def get_node(
        community_id: Identifier,
        node_id: Identifier,
        svc: Service,
        ctx: Annotated[AdminContext, permission("property.housing.read")],
    ) -> schema.SpaceNode:
        return svc.get_node(ctx, community_id, node_id)

    @router.patch(
        "/space-nodes/{node_id}",
        response_model=schema.SpaceNode,
        operation_id="updateSpaceNode",
        dependencies=[Depends(check_write)],
        responses=ok,
    )
    def update_node(
        community_id: Identifier,
        node_id: Identifier,
        data: schema.SpaceNodeUpdate,
        request: Request,
        svc: Service,
        ctx: Annotated[AdminContext, permission("property.housing.manage")],
    ) -> schema.SpaceNode:
        return svc.update_node(ctx, community_id, node_id, data, request.state.request_id)

    @router.get("/houses", response_model=schema.HousePage, operation_id="listHouses", responses=ok)
    def list_houses(
        community_id: Identifier,
        svc: Service,
        ctx: Annotated[AdminContext, permission("property.housing.read")],
        space_node_id: Identifier | None = None,
        room_no: Annotated[str | None, Query(max_length=32)] = None,
        external_code: Annotated[str | None, Query(max_length=64)] = None,
        floor_no: Annotated[int | None, Query(ge=-32768, le=32767)] = None,
        enabled: bool | None = None,
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 20,
        sort: Literal["created_at", "-created_at"] = "-created_at",
    ) -> schema.HousePage:
        return svc.list_houses(
            ctx,
            community_id,
            space_node_id=space_node_id,
            room_no=room_no,
            external_code=external_code,
            floor_no=floor_no,
            enabled=enabled,
            page=page,
            page_size=page_size,
            sort=sort,
        )

    @router.post(
        "/houses",
        response_model=schema.House,
        status_code=201,
        operation_id="createHouse",
        dependencies=[Depends(check_write)],
        responses=created,
    )
    def create_house(
        community_id: Identifier,
        data: schema.HouseCreate,
        request: Request,
        svc: Service,
        ctx: Annotated[AdminContext, permission("property.housing.manage")],
    ) -> schema.House:
        return svc.create_house(ctx, community_id, data, request.state.request_id)

    @router.get(
        "/houses/{house_id}", response_model=schema.House, operation_id="getHouse", responses=ok
    )
    def get_house(
        community_id: Identifier,
        house_id: Identifier,
        svc: Service,
        ctx: Annotated[AdminContext, permission("property.housing.read")],
    ) -> schema.House:
        return svc.get_house(ctx, community_id, house_id)

    @router.patch(
        "/houses/{house_id}",
        response_model=schema.House,
        operation_id="updateHouse",
        dependencies=[Depends(check_write)],
        responses=ok,
    )
    def update_house(
        community_id: Identifier,
        house_id: Identifier,
        data: schema.HouseUpdate,
        request: Request,
        svc: Service,
        ctx: Annotated[AdminContext, permission("property.housing.manage")],
    ) -> schema.House:
        return svc.update_house(ctx, community_id, house_id, data, request.state.request_id)

    @router.get(
        "/houses/{house_id}/owners",
        response_model=schema.HouseOwnerPage,
        operation_id="listHouseOwners",
        responses=ok,
    )
    def list_owners(
        community_id: Identifier,
        house_id: Identifier,
        svc: Service,
        ctx: Annotated[AdminContext, permission("property.housing.read")],
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 20,
        sort: Literal["created_at", "-created_at"] = "-created_at",
    ) -> schema.HouseOwnerPage:
        return svc.list_owners(
            ctx, community_id, house_id, page=page, page_size=page_size, sort=sort
        )

    @router.post(
        "/houses/{house_id}/owners",
        response_model=schema.HouseOwner,
        status_code=201,
        operation_id="createHouseOwner",
        dependencies=[Depends(check_write)],
        responses=created,
    )
    def create_owner(
        community_id: Identifier,
        house_id: Identifier,
        data: schema.HouseOwnerCreate,
        request: Request,
        svc: Service,
        ctx: Annotated[AdminContext, permission("property.housing.manage")],
    ) -> schema.HouseOwner:
        return svc.create_owner(ctx, community_id, house_id, data, request.state.request_id)

    @router.get(
        "/houses/{house_id}/owners/{owner_id}",
        response_model=schema.HouseOwner,
        operation_id="getHouseOwner",
        responses=ok,
    )
    def get_owner(
        community_id: Identifier,
        house_id: Identifier,
        owner_id: Identifier,
        svc: Service,
        ctx: Annotated[AdminContext, permission("property.housing.read")],
    ) -> schema.HouseOwner:
        return svc.get_owner(ctx, community_id, house_id, owner_id)

    @router.patch(
        "/houses/{house_id}/owners/{owner_id}",
        response_model=schema.HouseOwner,
        operation_id="updateHouseOwner",
        dependencies=[Depends(check_write)],
        responses=ok,
    )
    def update_owner(
        community_id: Identifier,
        house_id: Identifier,
        owner_id: Identifier,
        data: schema.HouseOwnerUpdate,
        request: Request,
        svc: Service,
        ctx: Annotated[AdminContext, permission("property.housing.manage")],
    ) -> schema.HouseOwner:
        return svc.update_owner(
            ctx, community_id, house_id, owner_id, data, request.state.request_id
        )

    return router
