from collections.abc import Sequence
from typing import cast

from backend_app.domain.housing import SpaceType, effective_enabled
from backend_app.models.housing import House, HouseOwner, SpaceNode
from backend_app.models.property import Community
from backend_app.schemas import housing as schema


def path_enabled(community: Community, path: Sequence[SpaceNode]) -> bool:
    return effective_enabled(community.enabled, (node.enabled for node in path))


def space_view(
    node: SpaceNode, community: Community, path: Sequence[SpaceNode], *, has_children: bool
) -> schema.SpaceNode:
    return schema.SpaceNode(
        id=node.id,
        community_id=node.community_id,
        parent_id=node.parent_id,
        node_type=cast(SpaceType, node.node_type),
        name=node.name,
        external_code=node.external_code,
        sort_order=node.sort_order,
        enabled=node.enabled,
        effective_enabled=path_enabled(community, path),
        has_children=has_children,
        ancestors=[schema.SpaceAncestor.model_validate(item) for item in path[:-1]],
        created_at=node.created_at,
        updated_at=node.updated_at,
    )


def house_view(house: House, community: Community, path: Sequence[SpaceNode]) -> schema.House:
    return schema.House(
        id=house.id,
        community_id=house.community_id,
        space_node_id=house.space_node_id,
        room_no=house.room_no,
        floor_no=house.floor_no,
        external_code=house.external_code,
        enabled=house.enabled,
        effective_enabled=house.enabled and path_enabled(community, path),
        display_address="／".join([community.name, *(node.name for node in path), house.room_no]),
        created_at=house.created_at,
        updated_at=house.updated_at,
    )


def owner_view(owner: HouseOwner, *, house_enabled: bool) -> schema.HouseOwner:
    return schema.HouseOwner(
        id=owner.id,
        house_id=owner.house_id,
        name=owner.name,
        phone=owner.phone,
        enabled=owner.enabled,
        effective_enabled=owner.enabled and house_enabled,
        created_at=owner.created_at,
        updated_at=owner.updated_at,
    )
