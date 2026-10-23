"""Transaction-participating housing creation for manual and batch entry points."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy.orm import Session

from backend_app.core.errors import AppError
from backend_app.domain.admin.identity import AdminIdentity
from backend_app.domain.housing import (
    HouseCreationCommand,
    create_house_records,
    house_creation_identity,
    house_creation_permissions,
    inspect_house_creation,
    revalidate_space_location,
    space_location_snapshot,
)
from backend_app.models.housing import House
from backend_app.repositories.admin import AdminRepository
from backend_app.repositories.housing import HousingRepository
from backend_app.repositories.property import PropertyRepository


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
    command: HouseCreationCommand,
    request_id: str,
    input_fields: frozenset[str],
    space_snapshot: Mapping[str, Any] | None = None,
    allow_existing: bool = False,
    expected_target_id: str | None = None,
) -> HouseCreationResult:
    """Protect resources and apply one creation; caller owns commit and rollback."""
    properties = PropertyRepository(db)
    company = properties.company(company_id, lock=True)
    if company is None or not company.enabled:
        raise AppError("auth.unauthenticated")
    identity = AdminIdentity(AdminRepository(db, "property_admin", company_id))
    actor = identity.account(actor_id, lock=True)
    if not actor.enabled:
        raise AppError("auth.unauthenticated")
    if actor.must_change_password:
        raise AppError("auth.password_change_required")
    if not house_creation_permissions(has_owners=bool(command.owners)) <= set(
        identity.effective_permissions(actor.id)
    ):
        raise AppError("auth.forbidden")
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
    identity.audit.record(
        actor=actor,
        action="property.house.create",
        target_type="house",
        target_id=house.id,
        request_id=request_id,
        metadata={"changed_fields": sorted(input_fields - {"owners"})},
    )
    for owner in owners:
        identity.audit.record(
            actor=actor,
            action="property.house_owner.create",
            target_type="house_owner",
            target_id=owner.id,
            request_id=request_id,
            metadata={"changed_fields": ["name", "phone"]},
        )
    db.flush()
    return HouseCreationResult("created", house)
