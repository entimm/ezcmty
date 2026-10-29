"""Property HTTP input and transaction adapter for shared housing use cases."""

from collections.abc import Callable
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend_app.core.errors import AppError
from backend_app.db.errors import is_unique_violation
from backend_app.domain.housing import HouseCreationCommand, HouseOwnerCreationCommand
from backend_app.schemas import housing as schema
from backend_app.services.contracts.admin import AdminContext
from backend_app.services.property_account_access import property_business_context
from backend_app.services.property_business.commands import FieldChanges, SpaceCreation
from backend_app.services.property_business.housing import HousingUseCases


class PropertyHousingService:
    def __init__(self, db: Session):
        self.db = db
        self.business = HousingUseCases(db)

    def _write[T](self, operation: Callable[[], T]) -> T:
        try:
            result = operation()
            self.db.commit()
            return result
        except IntegrityError as error:
            self.db.rollback()
            for constraint, code in (
                ("uq_space_node_sibling_name", "property.duplicate_space_name"),
                ("uq_house_room_no", "property.duplicate_room_no"),
                ("uq_house_owner_contact", "property.duplicate_house_owner"),
            ):
                if is_unique_violation(error, constraint):
                    raise AppError(code) from error
            raise
        except Exception:
            self.db.rollback()
            raise

    def list_nodes(
        self,
        context: AdminContext,
        community_id: str,
        *,
        parent_id: str | None,
        page: int,
        page_size: int,
    ) -> schema.SpaceNodePage:
        return self.business.list_nodes(
            property_business_context(self.db, context),
            community_id,
            parent_id=parent_id,
            page=page,
            page_size=page_size,
        )

    def get_node(self, context: AdminContext, community_id: str, node_id: str) -> schema.SpaceNode:
        return self.business.get_node(
            property_business_context(self.db, context), community_id, node_id
        )

    def create_node(
        self,
        context: AdminContext,
        community_id: str,
        data: schema.SpaceNodeCreate,
        request_id: str,
    ) -> schema.SpaceNode:
        return self._write(
            lambda: self.business.create_node(
                property_business_context(self.db, context),
                community_id,
                SpaceCreation(**data.model_dump(), input_fields=frozenset(data.model_fields_set)),
                request_id,
            )
        )

    def update_node(
        self,
        context: AdminContext,
        community_id: str,
        node_id: str,
        data: schema.SpaceNodeUpdate,
        request_id: str,
    ) -> schema.SpaceNode:
        return self._write(
            lambda: self.business.update_node(
                property_business_context(self.db, context),
                community_id,
                node_id,
                FieldChanges(data.model_dump(exclude_unset=True)),
                request_id,
            )
        )

    def list_houses(
        self, context: AdminContext, community_id: str, **filters: Any
    ) -> schema.HousePage:
        return self.business.list_houses(
            property_business_context(self.db, context), community_id, **filters
        )

    def get_house(self, context: AdminContext, community_id: str, house_id: str) -> schema.House:
        return self.business.get_house(
            property_business_context(self.db, context), community_id, house_id
        )

    def house_options(
        self, context: AdminContext, community_id: str, **filters: Any
    ) -> schema.HouseOptionPage:
        return self.business.house_options(
            property_business_context(self.db, context), community_id, **filters
        )

    def create_house(
        self, context: AdminContext, community_id: str, data: schema.HouseCreate, request_id: str
    ) -> schema.House:
        return self._write(
            lambda: self.business.create_house(
                property_business_context(self.db, context),
                community_id,
                HouseCreationCommand.from_input(data.model_dump()),
                request_id,
                input_fields=frozenset(data.model_fields_set),
            )
        )

    def update_house(
        self,
        context: AdminContext,
        community_id: str,
        house_id: str,
        data: schema.HouseUpdate,
        request_id: str,
    ) -> schema.House:
        return self._write(
            lambda: self.business.update_house(
                property_business_context(self.db, context),
                community_id,
                house_id,
                FieldChanges(data.model_dump(exclude_unset=True)),
                request_id,
            )
        )

    def list_owners(
        self, context: AdminContext, community_id: str, house_id: str, **filters: Any
    ) -> schema.HouseOwnerPage:
        return self.business.list_owners(
            property_business_context(self.db, context), community_id, house_id, **filters
        )

    def get_owner(
        self, context: AdminContext, community_id: str, house_id: str, owner_id: str
    ) -> schema.HouseOwner:
        return self.business.get_owner(
            property_business_context(self.db, context), community_id, house_id, owner_id
        )

    def create_owner(
        self,
        context: AdminContext,
        community_id: str,
        house_id: str,
        data: schema.HouseOwnerCreate,
        request_id: str,
    ) -> schema.HouseOwner:
        return self._write(
            lambda: self.business.create_owner(
                property_business_context(self.db, context),
                community_id,
                house_id,
                HouseOwnerCreationCommand.from_input({"house_id": house_id, **data.model_dump()}),
                request_id,
            )
        )

    def update_owner(
        self,
        context: AdminContext,
        community_id: str,
        house_id: str,
        owner_id: str,
        data: schema.HouseOwnerUpdate,
        request_id: str,
    ) -> schema.HouseOwner:
        return self._write(
            lambda: self.business.update_owner(
                property_business_context(self.db, context),
                community_id,
                house_id,
                owner_id,
                FieldChanges(data.model_dump(exclude_unset=True)),
                request_id,
            )
        )
