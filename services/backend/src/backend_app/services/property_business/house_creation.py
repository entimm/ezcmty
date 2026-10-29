"""Transaction-participating housing creation for manual and batch entry points."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy.orm import Session

from backend_app.core.errors import AppError
from backend_app.domain.housing import (
    HouseCreationCommand,
    create_house_records,
    house_creation_identity,
    inspect_house_creation,
    revalidate_space_location,
    space_location_snapshot,
)
from backend_app.models.housing import House
from backend_app.repositories.housing import HousingRepository
from backend_app.repositories.property import PropertyRepository
from backend_app.services.property_business.context import PropertyBusinessContext
from backend_app.services.property_business.house_owner_creation import audit_house_owner_creation


@dataclass(frozen=True)
class HouseCreationResult:
    status: Literal["created", "skipped"]
    house: House


def prepare_house_creation(
    db: Session,
    *,
    company_id: str,
    community_id: str,
    command: HouseCreationCommand,
    space_snapshot: Mapping[str, Any] | None = None,
    target_id: str | None = None,
    lock: bool = False,
) -> dict[str, Any]:
    repo = HousingRepository(db, company_id)
    snapshot = (
        revalidate_space_location(repo, community_id, space_snapshot, lock=lock)
        if space_snapshot is not None
        else space_location_snapshot(repo, community_id, command.space_node_id, lock=lock)
    )
    if snapshot["space_node_id"] != command.space_node_id:
        raise AppError("property.house_location_changed")
    if not snapshot["effective_enabled"]:
        raise AppError("property.housing_disabled")
    existing = inspect_house_creation(repo, community_id, command, target_id=target_id, lock=lock)
    return {
        "action": "skip" if existing else "create",
        "target_id": existing.id if existing else None,
        "natural_key": house_creation_identity(command.space_node_id, command.room_no),
        "input_fingerprint": command.fingerprint(),
        "space_snapshot": snapshot,
        "command": command.to_dict(),
        "house_label": "／".join(
            [
                snapshot["community_name"],
                *(node["name"] for node in snapshot["path"]),
                command.room_no,
            ]
        ),
    }


def create_house(
    db: Session,
    *,
    company_id: str,
    community_id: str,
    actor_id: str,
    context: PropertyBusinessContext,
    command: HouseCreationCommand,
    request_id: str,
    input_fields: frozenset[str],
    space_snapshot: Mapping[str, Any] | None = None,
    allow_existing: bool = False,
    expected_target_id: str | None = None,
) -> HouseCreationResult:
    """Protect resources and apply one creation; caller owns commit and rollback."""
    if context.company_id != company_id or context.actor_id != actor_id:
        raise AppError("auth.forbidden")
    actor = context.require("housing.manage", lock=True)
    properties = PropertyRepository(db)
    community = properties.community(community_id, company_scope_id=company_id, lock=True)
    if community is None:
        raise AppError("resource.not_found")
    if allow_existing and command.owners:
        raise AppError("VALIDATION_ERROR")
    prepared = prepare_house_creation(
        db,
        company_id=company_id,
        community_id=community_id,
        command=command,
        space_snapshot=space_snapshot,
        target_id=expected_target_id,
        lock=True,
    )
    repo = HousingRepository(db, company_id)
    if prepared["target_id"] is not None:
        if not allow_existing:
            raise AppError("property.duplicate_room_no")
        existing = repo.house(community_id, prepared["target_id"])
        assert existing is not None
        return HouseCreationResult("skipped", existing)
    house, owners = create_house_records(repo, community_id, command)
    context.record(
        actor=actor,
        action="property.house.create",
        target_type="house",
        target_id=house.id,
        request_id=request_id,
        metadata={"changed_fields": sorted(input_fields - {"owners"})},
    )
    for owner in owners:
        audit_house_owner_creation(context, actor, owner, request_id)
    db.flush()
    return HouseCreationResult("created", house)
