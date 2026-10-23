from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend_app.core.errors import AppError
from backend_app.core.identifiers import new_id
from backend_app.db.errors import is_unique_violation
from backend_app.domain.admin.identity import AdminIdentity
from backend_app.domain.housing import (
    HouseCreationCommand,
    HouseOwnerCreationCommand,
    effective_enabled,
    house_creation_permissions,
    is_valid_space_parent,
)
from backend_app.models.admin import AdminAccount, utc_now
from backend_app.models.housing import House, HouseOwner, SpaceNode
from backend_app.models.property import Community
from backend_app.repositories.admin import AdminRepository
from backend_app.repositories.housing import HousingRepository
from backend_app.repositories.property import PropertyRepository
from backend_app.schemas import housing as schema
from backend_app.schemas.mappers.housing import house_view, owner_view, space_view
from backend_app.services.contracts.admin import AdminContext
from backend_app.services.house_creation import create_house
from backend_app.services.house_owner_creation import create_house_owner


class PropertyHousingService:
    def __init__(self, db: Session):
        self.db = db
        self.properties = PropertyRepository(db)

    def _scope(
        self, context: AdminContext, permission: str
    ) -> tuple[HousingRepository, AdminIdentity]:
        identity = AdminIdentity(
            AdminRepository(self.db, "property_admin", context.property_company_id)
        )
        identity.require_permission(context, permission)
        if context.property_company_id is None:
            raise AppError("auth.forbidden")
        return HousingRepository(self.db, context.property_company_id), identity

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
        self, context: AdminContext, permission: str, community_id: str
    ) -> tuple[HousingRepository, Community]:
        repo, _ = self._scope(context, permission)
        return repo, self._community(repo, community_id)

    def _write(
        self, context: AdminContext, permission: str, community_id: str
    ) -> tuple[HousingRepository, AdminIdentity, AdminAccount, Community]:
        repo, identity = self._scope(context, permission)
        # Match platform company/account changes, then serialize this community's mutations.
        company = self.properties.company(repo.company_id, lock=True)
        if company is None or not company.enabled:
            raise AppError("auth.unauthenticated")
        actor = identity.actor(context)
        if actor.must_change_password:
            raise AppError("auth.password_change_required")
        if permission not in identity.effective_permissions(actor.id):
            raise AppError("auth.forbidden")
        return repo, identity, actor, self._community(repo, community_id, lock=True)

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
        return house, path

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
        identity: AdminIdentity,
        actor: AdminAccount,
        action: str,
        target_type: str,
        target_id: str,
        request_id: str,
        fields: list[str],
    ) -> None:
        identity.audit.record(
            actor=actor,
            action=action,
            target_type=target_type,
            target_id=target_id,
            request_id=request_id,
            metadata={"changed_fields": fields},
        )

    def _commit(self) -> None:
        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            for constraint, code in (
                ("uq_space_node_sibling_name", "property.duplicate_space_name"),
                ("uq_house_room_no", "property.duplicate_room_no"),
                ("uq_house_owner_contact", "property.duplicate_house_owner"),
            ):
                if is_unique_violation(exc, constraint):
                    raise AppError(code) from exc
            raise

    def _update(
        self, record: SpaceNode | House | HouseOwner, data: schema.HousingUpdate
    ) -> list[str]:
        fields = []
        for field, value in data.model_dump(exclude_unset=True).items():
            if getattr(record, field) != value:
                setattr(record, field, value)
                fields.append(field)
        if fields:
            record.updated_at = utc_now()
        return fields

    def list_nodes(
        self,
        context: AdminContext,
        community_id: str,
        *,
        parent_id: str | None,
        page: int,
        page_size: int,
    ) -> schema.SpaceNodePage:
        repo, community = self._read(context, "property.space.read", community_id)
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

    def get_node(self, context: AdminContext, community_id: str, node_id: str) -> schema.SpaceNode:
        repo, community = self._read(context, "property.space.read", community_id)
        path = self._path(repo, community_id, node_id)
        return space_view(
            path[-1], community, path, has_children=repo.has_children(community_id, node_id)
        )

    def create_node(
        self,
        context: AdminContext,
        community_id: str,
        data: schema.SpaceNodeCreate,
        request_id: str,
    ) -> schema.SpaceNode:
        repo, identity, actor, community = self._write(
            context, "property.space.create", community_id
        )
        path = self._path(repo, community_id, data.parent_id, lock=True) if data.parent_id else []
        if not is_valid_space_parent(data.node_type, path[-1].node_type if path else None):
            raise AppError("property.invalid_space_parent")
        self._require_enabled(community, path)
        now = utc_now()
        node = SpaceNode(
            id=new_id(),
            community_id=community_id,
            **data.model_dump(),
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
            list(data.model_fields_set),
        )
        self._commit()
        return space_view(node, community, [*path, node], has_children=False)

    def update_node(
        self,
        context: AdminContext,
        community_id: str,
        node_id: str,
        data: schema.SpaceNodeUpdate,
        request_id: str,
    ) -> schema.SpaceNode:
        repo, identity, actor, community = self._write(
            context, "property.space.update", community_id
        )
        path = self._path(repo, community_id, node_id, lock=True)
        node = path[-1]
        fields = self._update(node, data)
        self._audit(
            identity, actor, "property.space.update", "space_node", node.id, request_id, fields
        )
        self._commit()
        return space_view(
            node, community, path, has_children=repo.has_children(community_id, node_id)
        )

    def list_houses(
        self, context: AdminContext, community_id: str, **filters: Any
    ) -> schema.HousePage:
        repo, community = self._read(context, "property.house.read", community_id)
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

    def get_house(self, context: AdminContext, community_id: str, house_id: str) -> schema.House:
        repo, community = self._read(context, "property.house.read", community_id)
        house, path = self._house(repo, community_id, house_id)
        return house_view(house, community, path)

    def create_house(
        self, context: AdminContext, community_id: str, data: schema.HouseCreate, request_id: str
    ) -> schema.House:
        repo, identity, actor, community = self._write(
            context, "property.house.create", community_id
        )
        if not house_creation_permissions(has_owners=bool(data.owners)) <= set(
            identity.effective_permissions(actor.id)
        ):
            raise AppError("auth.forbidden")
        try:
            result = create_house(
                self.db,
                company_id=repo.company_id,
                community_id=community_id,
                actor_id=actor.id,
                command=HouseCreationCommand.from_input(data.model_dump()),
                request_id=request_id,
                input_fields=frozenset(data.model_fields_set),
            )
        except IntegrityError as exc:
            self.db.rollback()
            for constraint, code in (
                ("uq_house_room_no", "property.duplicate_room_no"),
                ("uq_house_owner_contact", "property.duplicate_house_owner"),
            ):
                if is_unique_violation(exc, constraint):
                    raise AppError(code) from exc
            raise
        self._commit()
        path = self._path(repo, community_id, result.house.space_node_id)
        return house_view(result.house, community, path)

    def update_house(
        self,
        context: AdminContext,
        community_id: str,
        house_id: str,
        data: schema.HouseUpdate,
        request_id: str,
    ) -> schema.House:
        repo, identity, actor, community = self._write(
            context, "property.house.update", community_id
        )
        house, path = self._house(repo, community_id, house_id, lock=True)
        fields = self._update(house, data)
        self._audit(identity, actor, "property.house.update", "house", house.id, request_id, fields)
        self._commit()
        return house_view(house, community, path)

    def list_owners(
        self, context: AdminContext, community_id: str, house_id: str, **filters: Any
    ) -> schema.HouseOwnerPage:
        repo, community = self._read(context, "property.house_owner.read", community_id)
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
        self, context: AdminContext, community_id: str, house_id: str, owner_id: str
    ) -> schema.HouseOwner:
        repo, community = self._read(context, "property.house_owner.read", community_id)
        house, path = self._house(repo, community_id, house_id)
        owner = repo.owner(community_id, house_id, owner_id)
        if owner is None:
            raise AppError("resource.not_found")
        return owner_view(owner, house_enabled=self._effective_enabled(community, path, house))

    def create_owner(
        self,
        context: AdminContext,
        community_id: str,
        house_id: str,
        data: schema.HouseOwnerCreate,
        request_id: str,
    ) -> schema.HouseOwner:
        repo, _, actor, _ = self._write(context, "property.house_owner.create", community_id)
        try:
            result = create_house_owner(
                self.db,
                company_id=repo.company_id,
                community_id=community_id,
                actor_id=actor.id,
                command=HouseOwnerCreationCommand.from_input(
                    {"house_id": house_id, **data.model_dump()}
                ),
                request_id=request_id,
            )
        except IntegrityError as exc:
            self.db.rollback()
            if is_unique_violation(exc, "uq_house_owner_contact"):
                raise AppError("property.duplicate_house_owner") from exc
            raise
        self._commit()
        return owner_view(result.owner, house_enabled=True)

    def update_owner(
        self,
        context: AdminContext,
        community_id: str,
        house_id: str,
        owner_id: str,
        data: schema.HouseOwnerUpdate,
        request_id: str,
    ) -> schema.HouseOwner:
        repo, identity, actor, community = self._write(
            context, "property.house_owner.update", community_id
        )
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
        self._commit()
        return owner_view(owner, house_enabled=self._effective_enabled(community, path, house))
