from typing import Any

from sqlalchemy.orm import Session

from backend_app.core.errors import AppError
from backend_app.core.identifiers import new_id
from backend_app.domain.housing import (
    HouseCreationCommand,
    HouseOwnerCreationCommand,
    effective_enabled,
    is_valid_space_parent,
    validate_housing_update,
)
from backend_app.models.admin import utc_now
from backend_app.models.housing import House, HouseOwner, SpaceNode
from backend_app.models.property import Community
from backend_app.repositories.housing import HousingRepository
from backend_app.repositories.property import PropertyRepository
from backend_app.schemas import housing as schema
from backend_app.schemas.mappers.housing import house_view, owner_view, space_view
from backend_app.services.property_business.commands import (
    FieldChanges,
    SpaceCreation,
)
from backend_app.services.property_business.context import BusinessActor, PropertyBusinessContext
from backend_app.services.property_business.house_creation import create_house
from backend_app.services.property_business.house_owner_creation import create_house_owner


class HousingUseCases:
    def __init__(self, db: Session):
        self.db = db
        self.properties = PropertyRepository(db)

    def _scope(
        self, context: PropertyBusinessContext, permission: str
    ) -> tuple[HousingRepository, PropertyBusinessContext]:
        context.require(permission)
        return (HousingRepository(self.db, context.company_id), context)

    def _community(
        self, repo: HousingRepository, community_id: str, *, lock: bool = False
    ) -> Community:
        community = self.properties.community(
            community_id, company_scope_id=repo.company_id, lock=lock
        )
        if community is None:
            raise AppError("resource.not_found")
        return community

    def _read(
        self, context: PropertyBusinessContext, permission: str, community_id: str
    ) -> tuple[HousingRepository, Community]:
        repo, _ = self._scope(context, permission)
        return (repo, self._community(repo, community_id))

    def _write(
        self, context: PropertyBusinessContext, permission: str, community_id: str
    ) -> tuple[HousingRepository, PropertyBusinessContext, BusinessActor, Community]:
        repo, identity = self._scope(context, permission)
        actor = context.require(permission, lock=True)
        return (repo, identity, actor, self._community(repo, community_id, lock=True))

    def _path(
        self, repo: HousingRepository, community_id: str, node_id: str, *, lock: bool = False
    ) -> list[SpaceNode]:
        path = repo.paths(community_id, [node_id]).get(node_id)
        if not path:
            raise AppError("resource.not_found")
        if lock:
            refreshed = []
            for node in path:
                current = repo.node(community_id, node.id, lock=True)
                if current is None:
                    raise AppError("resource.not_found")
                refreshed.append(current)
            return refreshed
        return path

    def _house(
        self, repo: HousingRepository, community_id: str, house_id: str, *, lock: bool = False
    ) -> tuple[House, list[SpaceNode]]:
        house = repo.house(community_id, house_id)
        if house is None:
            raise AppError("resource.not_found")
        path = self._path(repo, community_id, house.space_node_id, lock=lock)
        if lock:
            house = repo.house(community_id, house_id, lock=True)
            if house is None:
                raise AppError("resource.not_found")
        return (house, path)

    def _effective_enabled(
        self, community: Community, path: list[SpaceNode], house: House | None = None
    ) -> bool:
        states = [node.enabled for node in path]
        if house is not None:
            states.append(house.enabled)
        return effective_enabled(community.enabled, states)

    def _require_enabled(
        self, community: Community, path: list[SpaceNode], house: House | None = None
    ) -> None:
        if not self._effective_enabled(community, path, house):
            raise AppError("property.housing_disabled")

    def _audit(
        self,
        identity: PropertyBusinessContext,
        actor: BusinessActor,
        action: str,
        target_type: str,
        target_id: str,
        request_id: str,
        fields: list[str],
    ) -> None:
        identity.record(
            actor=actor,
            action=action,
            target_type=target_type,
            target_id=target_id,
            request_id=request_id,
            metadata={"changed_fields": fields},
        )

    def _update(self, record: SpaceNode | House | HouseOwner, data: FieldChanges) -> list[str]:
        kind = {SpaceNode: "space", House: "house", HouseOwner: "owner"}[type(record)]
        values = validate_housing_update(kind, data.values)
        fields = []
        for field, value in values.items():
            if getattr(record, field) != value:
                setattr(record, field, value)
                fields.append(field)
        if fields:
            record.updated_at = utc_now()
        return fields

    def list_nodes(
        self,
        context: PropertyBusinessContext,
        community_id: str,
        *,
        parent_id: str | None,
        page: int,
        page_size: int,
    ) -> schema.SpaceNodePage:
        repo, community = self._read(context, "housing.read", community_id)
        if parent_id is not None:
            self._path(repo, community_id, parent_id)
        items, total = repo.nodes(community_id, parent_id=parent_id, page=page, page_size=page_size)
        paths = repo.paths(community_id, [node.id for node, _ in items])
        return schema.SpaceNodePage(
            items=[
                space_view(node, community, paths[node.id], has_children=children)
                for node, children in items
            ],
            total=total,
            page=page,
            page_size=page_size,
        )

    def get_node(
        self, context: PropertyBusinessContext, community_id: str, node_id: str
    ) -> schema.SpaceNode:
        repo, community = self._read(context, "housing.read", community_id)
        path = self._path(repo, community_id, node_id)
        return space_view(
            path[-1], community, path, has_children=repo.has_children(community_id, node_id)
        )

    def create_node(
        self,
        context: PropertyBusinessContext,
        community_id: str,
        data: SpaceCreation,
        request_id: str,
    ) -> schema.SpaceNode:
        repo, identity, actor, community = self._write(context, "housing.manage", community_id)
        path = self._path(repo, community_id, data.parent_id, lock=True) if data.parent_id else []
        if not is_valid_space_parent(data.node_type, path[-1].node_type if path else None):
            raise AppError("property.invalid_space_parent")
        self._require_enabled(community, path)
        now = utc_now()
        node = SpaceNode(
            id=new_id(),
            community_id=community_id,
            node_type=data.node_type,
            name=data.name,
            parent_id=data.parent_id,
            external_code=data.external_code,
            sort_order=data.sort_order,
            enabled=True,
            created_at=now,
            updated_at=now,
        )
        self.db.add(node)
        self._audit(
            identity,
            actor,
            "property.space.create",
            "space_node",
            node.id,
            request_id,
            list(data.input_fields),
        )
        return space_view(node, community, [*path, node], has_children=False)

    def update_node(
        self,
        context: PropertyBusinessContext,
        community_id: str,
        node_id: str,
        data: FieldChanges,
        request_id: str,
    ) -> schema.SpaceNode:
        repo, identity, actor, community = self._write(context, "housing.manage", community_id)
        path = self._path(repo, community_id, node_id, lock=True)
        node = path[-1]
        fields = self._update(node, data)
        self._audit(
            identity, actor, "property.space.update", "space_node", node.id, request_id, fields
        )
        return space_view(
            node, community, path, has_children=repo.has_children(community_id, node_id)
        )

    def list_houses(
        self, context: PropertyBusinessContext, community_id: str, **filters: Any
    ) -> schema.HousePage:
        repo, community = self._read(context, "housing.read", community_id)
        if filters.get("space_node_id") is not None:
            self._path(repo, community_id, filters["space_node_id"])
        items, total = repo.houses(community_id, **filters)
        paths = repo.paths(community_id, [house.space_node_id for house in items])
        return schema.HousePage(
            items=[house_view(house, community, paths[house.space_node_id]) for house in items],
            total=total,
            page=filters["page"],
            page_size=filters["page_size"],
        )

    def get_house(
        self, context: PropertyBusinessContext, community_id: str, house_id: str
    ) -> schema.House:
        repo, community = self._read(context, "housing.read", community_id)
        house, path = self._house(repo, community_id, house_id)
        return house_view(house, community, path)

    def house_options(
        self, context: PropertyBusinessContext, community_id: str, **filters: Any
    ) -> schema.HouseOptionPage:
        allowed = {"bill.read", "resident_access.read", "housing.read"}
        permission = next((code for code in context.require().permissions if code in allowed), None)
        if permission is None:
            raise AppError("auth.forbidden")
        repo, community = self._read(context, permission, community_id)
        items, total = repo.houses(community_id, sort="-created_at", **filters)
        paths = repo.paths(community_id, [house.space_node_id for house in items])
        values = [house_view(house, community, paths[house.space_node_id]) for house in items]
        return schema.HouseOptionPage(
            items=[
                schema.HouseOption(
                    id=item.id,
                    community_id=item.community_id,
                    label=item.display_address,
                    enabled=item.enabled,
                    effective_enabled=item.effective_enabled,
                )
                for item in values
            ],
            total=total,
            page=filters["page"],
            page_size=filters["page_size"],
        )

    def create_house(
        self,
        context: PropertyBusinessContext,
        community_id: str,
        data: HouseCreationCommand,
        request_id: str,
        input_fields: frozenset[str],
    ) -> schema.House:
        repo, identity, actor, community = self._write(context, "housing.manage", community_id)
        if not frozenset({"housing.manage"}) <= set(actor.permissions):
            raise AppError("auth.forbidden")
        result = create_house(
            self.db,
            company_id=repo.company_id,
            community_id=community_id,
            actor_id=actor.id,
            context=context,
            command=data,
            request_id=request_id,
            input_fields=input_fields,
        )
        path = self._path(repo, community_id, result.house.space_node_id)
        return house_view(result.house, community, path)

    def update_house(
        self,
        context: PropertyBusinessContext,
        community_id: str,
        house_id: str,
        data: FieldChanges,
        request_id: str,
    ) -> schema.House:
        repo, identity, actor, community = self._write(context, "housing.manage", community_id)
        house, path = self._house(repo, community_id, house_id, lock=True)
        fields = self._update(house, data)
        self._audit(identity, actor, "property.house.update", "house", house.id, request_id, fields)
        return house_view(house, community, path)

    def list_owners(
        self, context: PropertyBusinessContext, community_id: str, house_id: str, **filters: Any
    ) -> schema.HouseOwnerPage:
        repo, community = self._read(context, "housing.read", community_id)
        house, path = self._house(repo, community_id, house_id)
        items, total = repo.owners(community_id, house_id, **filters)
        enabled = self._effective_enabled(community, path, house)
        return schema.HouseOwnerPage(
            items=[owner_view(item, house_enabled=enabled) for item in items],
            total=total,
            page=filters["page"],
            page_size=filters["page_size"],
        )

    def get_owner(
        self, context: PropertyBusinessContext, community_id: str, house_id: str, owner_id: str
    ) -> schema.HouseOwner:
        repo, community = self._read(context, "housing.read", community_id)
        house, path = self._house(repo, community_id, house_id)
        owner = repo.owner(community_id, house_id, owner_id)
        if owner is None:
            raise AppError("resource.not_found")
        return owner_view(owner, house_enabled=self._effective_enabled(community, path, house))

    def create_owner(
        self,
        context: PropertyBusinessContext,
        community_id: str,
        house_id: str,
        data: HouseOwnerCreationCommand,
        request_id: str,
    ) -> schema.HouseOwner:
        if data.house_id != house_id:
            raise AppError("VALIDATION_ERROR")
        repo, _, actor, _ = self._write(context, "housing.manage", community_id)
        result = create_house_owner(
            self.db,
            company_id=repo.company_id,
            community_id=community_id,
            actor_id=actor.id,
            context=context,
            command=data,
            request_id=request_id,
        )
        return owner_view(result.owner, house_enabled=True)

    def update_owner(
        self,
        context: PropertyBusinessContext,
        community_id: str,
        house_id: str,
        owner_id: str,
        data: FieldChanges,
        request_id: str,
    ) -> schema.HouseOwner:
        repo, identity, actor, community = self._write(context, "housing.manage", community_id)
        house, path = self._house(repo, community_id, house_id, lock=True)
        owner = repo.owner(community_id, house_id, owner_id, lock=True)
        if owner is None:
            raise AppError("resource.not_found")
        fields = self._update(owner, data)
        self._audit(
            identity,
            actor,
            "property.house_owner.update",
            "house_owner",
            owner.id,
            request_id,
            fields,
        )
        return owner_view(owner, house_enabled=self._effective_enabled(community, path, house))
