"""Shared owner registration; entry points own their transaction and input protocol."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy.orm import Session

from backend_app.core.errors import AppError
from backend_app.domain.housing import (
    HouseOwnerCreationCommand,
    create_house_owner_record,
    house_location_snapshot,
    inspect_house_owner_creation,
    revalidate_house_location,
)
from backend_app.models.housing import HouseOwner
from backend_app.repositories.housing import HousingRepository
from backend_app.repositories.property import PropertyRepository
from backend_app.services.property_business.context import BusinessActor, PropertyBusinessContext


@dataclass(frozen=True)
class HouseOwnerCreationResult:
    status: Literal["created", "skipped"]
    owner: HouseOwner


def prepare_house_owner_creation(
    db: Session,
    *,
    company_id: str,
    community_id: str,
    command: HouseOwnerCreationCommand,
    house_snapshot: Mapping[str, Any] | None = None,
    target_id: str | None = None,
    lock: bool = False,
) -> dict[str, Any]:
    repo = HousingRepository(db, company_id)
    snapshot = (
        revalidate_house_location(repo, community_id, house_snapshot, lock=lock, exclusive=True)
        if house_snapshot is not None
        else house_location_snapshot(
            repo, community_id, command.house_id, lock=lock, exclusive=True
        )
    )
    if snapshot["house_id"] != command.house_id:
        raise AppError("property.house_location_changed")
    if not snapshot["effective_enabled"]:
        raise AppError("property.housing_disabled")
    existing = inspect_house_owner_creation(
        repo, community_id, command, target_id=target_id, lock=lock
    )
    return {
        "action": "skip" if existing else "create",
        "target_id": existing.id if existing else None,
        "natural_key": command.to_dict(),
        "input_fingerprint": command.fingerprint(),
        "house_snapshot": snapshot,
        "command": command.to_dict(),
        "owner_enabled": existing.enabled if existing else None,
        "house_label": "／".join(
            [
                snapshot["community_name"],
                *(node["name"] for node in snapshot["path"]),
                snapshot["room_no"],
            ]
        ),
    }


def audit_house_owner_creation(
    context: PropertyBusinessContext, actor: BusinessActor, owner: HouseOwner, request_id: str
) -> None:
    context.record(
        actor=actor,
        action="property.house_owner.create",
        target_type="house_owner",
        target_id=owner.id,
        request_id=request_id,
        metadata={"changed_fields": ["name", "phone"]},
    )


def _protect_house_owner_creation(
    db: Session,
    *,
    company_id: str,
    community_id: str,
    actor_id: str,
    context: PropertyBusinessContext,
) -> tuple[PropertyBusinessContext, BusinessActor]:
    if context.company_id != company_id or context.actor_id != actor_id:
        raise AppError("auth.forbidden")
    actor = context.require("housing.manage", lock=True)
    properties = PropertyRepository(db)
    community = properties.community(community_id, company_scope_id=company_id, lock=True)
    if community is None:
        raise AppError("resource.not_found")
    return context, actor


def revalidate_house_owner_creation(
    db: Session,
    *,
    company_id: str,
    community_id: str,
    actor_id: str,
    context: PropertyBusinessContext,
    command: HouseOwnerCreationCommand,
    house_snapshot: Mapping[str, Any],
    target_id: str,
) -> dict[str, Any]:
    """Protect an existing result until the caller finishes its transaction; write nothing."""
    _protect_house_owner_creation(
        db, company_id=company_id, community_id=community_id, actor_id=actor_id, context=context
    )
    return prepare_house_owner_creation(
        db,
        company_id=company_id,
        community_id=community_id,
        command=command,
        house_snapshot=house_snapshot,
        target_id=target_id,
        lock=True,
    )


def create_house_owner(
    db: Session,
    *,
    company_id: str,
    community_id: str,
    actor_id: str,
    context: PropertyBusinessContext,
    command: HouseOwnerCreationCommand,
    request_id: str,
    house_snapshot: Mapping[str, Any] | None = None,
    allow_existing: bool = False,
    expected_target_id: str | None = None,
) -> HouseOwnerCreationResult:
    """Protect resources and register one owner without committing or rolling back."""
    context, actor = _protect_house_owner_creation(
        db, company_id=company_id, community_id=community_id, actor_id=actor_id, context=context
    )
    prepared = prepare_house_owner_creation(
        db,
        company_id=company_id,
        community_id=community_id,
        command=command,
        house_snapshot=house_snapshot,
        target_id=expected_target_id,
        lock=True,
    )
    repo = HousingRepository(db, company_id)
    if prepared["target_id"] is not None:
        if not allow_existing:
            raise AppError("property.duplicate_house_owner")
        existing = repo.owner(community_id, command.house_id, prepared["target_id"])
        assert existing is not None
        return HouseOwnerCreationResult("skipped", existing)
    owner = create_house_owner_record(repo, command)
    audit_house_owner_creation(context, actor, owner, request_id)
    db.flush()
    return HouseOwnerCreationResult("created", owner)
