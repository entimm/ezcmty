"""Transaction-participating fee-basis creation for manual and batch entry."""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy.orm import Session

from backend_app.core.errors import AppError
from backend_app.core.identifiers import new_id
from backend_app.domain.admin.identity import AdminIdentity
from backend_app.domain.billing.basis import (
    BASIS_CONTENT_FIELDS,
    FeeBasisCreationCommand,
    fee_basis_fingerprint,
    matches_fee_basis,
    validate_basis_version_number,
)
from backend_app.domain.billing.calculation import MAX_CENTS, month_date
from backend_app.domain.housing import house_location_snapshot, revalidate_house_location
from backend_app.models.admin import AdminAccount, utc_now
from backend_app.models.billing import FeeBasisVersion
from backend_app.repositories.admin import AdminRepository
from backend_app.repositories.billing import BillingRepository


@dataclass(frozen=True)
class FeeBasisCreationResult:
    status: Literal["created", "skipped"]
    basis: FeeBasisVersion


def _protect_fee_basis(
    db: Session,
    repo: BillingRepository,
    company_id: str,
    community_id: str,
    actor_id: str,
) -> tuple[AdminIdentity, AdminAccount]:
    identity = AdminIdentity(AdminRepository(db, "property_admin", company_id))
    company, actor, community = repo.protect(actor_id, community_id)
    if company is None or not company.enabled or actor is None or not actor.enabled:
        raise AppError("auth.unauthenticated")
    if actor.must_change_password:
        raise AppError("auth.password_change_required")
    if community is None:
        raise AppError("resource.not_found")
    if "property.fee_basis.manage" not in identity.effective_permissions(actor.id):
        raise AppError("auth.forbidden")
    return identity, actor


def _resolve_house(
    repo: BillingRepository,
    community_id: str,
    command: FeeBasisCreationCommand,
    house_snapshot: Mapping[str, Any] | None,
    *,
    lock: bool = False,
    exclusive: bool = False,
) -> dict[str, Any]:
    resolved = (
        revalidate_house_location(
            repo.housing, community_id, house_snapshot, lock=lock, exclusive=exclusive
        )
        if house_snapshot is not None
        else house_location_snapshot(
            repo.housing, community_id, command.house_id, lock=lock, exclusive=exclusive
        )
    )
    if resolved["house_id"] != command.house_id:
        raise AppError("property.house_location_changed")
    if not resolved["effective_enabled"]:
        raise AppError("property.housing_disabled")
    return resolved


def prepare_fee_basis_creation(
    db: Session,
    *,
    company_id: str,
    community_id: str,
    command: FeeBasisCreationCommand,
    house_snapshot: Mapping[str, Any] | None = None,
    expected_latest_version_no: int | None = None,
    expected_action: str | None = None,
    expected_target_id: str | None = None,
    lock: bool = False,
) -> dict[str, Any]:
    """Prepare a new operation, or revalidate its fixed action and full-house baseline."""
    repo = BillingRepository(db, company_id)
    resolved = _resolve_house(
        repo, community_id, command, house_snapshot, lock=lock, exclusive=lock
    )
    number = repo.latest_basis_number(command.house_id)
    if expected_latest_version_no is not None:
        validate_basis_version_number(expected_latest_version_no)
        if number != expected_latest_version_no:
            raise AppError("billing.basis_version_conflict")
    comparison = repo.latest_basis_for_month(
        command.house_id, month_date(command.effective_from_month)
    )
    same = comparison is not None and matches_fee_basis(command, comparison)
    action = "skip" if same else "create"
    target_id = comparison.id if same and comparison is not None else None
    if expected_action is not None and (
        expected_action not in {"create", "skip"}
        or action != expected_action
        or target_id != expected_target_id
    ):
        raise AppError("billing.basis_version_conflict")
    old = FeeBasisCreationCommand.from_basis(comparison).to_dict() if comparison else None
    new = command.to_dict()
    following = repo.next_basis_month(command.house_id, month_date(command.effective_from_month))
    return {
        "command": new,
        "house_snapshot": dict(house_snapshot) if house_snapshot is not None else resolved,
        "natural_key": {"house_id": command.house_id},
        "input_fingerprint": fee_basis_fingerprint(command, resolved, number),
        "expected_latest_version_no": number,
        "comparison_version_id": comparison.id if comparison else None,
        "comparison_version_no": comparison.version_no if comparison else None,
        "old_basis": old,
        "new_basis": new,
        "changed_fields": [
            key for key in BASIS_CONTENT_FIELDS if old is None or old[key] != new[key]
        ],
        "calculated_amount_cents": command.calculated_amount(),
        "next_effective_month": (
            f"{following.year:04d}-{following.month:02d}" if following is not None else None
        ),
        "house_label": "／".join(
            [
                resolved["community_name"],
                *(node["name"] for node in resolved["path"]),
                resolved["room_no"],
            ]
        ),
        "action": action,
        "target_id": target_id,
    }


def verify_fee_basis_result(
    db: Session,
    *,
    company_id: str,
    community_id: str,
    command: FeeBasisCreationCommand,
    target_id: str,
    original_status: str,
    house_snapshot: Mapping[str, Any] | None = None,
    expected_latest_version_no: int | None = None,
    expected_target_id: str | None = None,
    actor_id: str | None = None,
    lock: bool = False,
) -> FeeBasisVersion:
    """Verify an original immutable result without requiring it to remain latest."""
    repo = BillingRepository(db, company_id)
    if lock:
        if actor_id is None:
            raise AppError("auth.forbidden")
        _protect_fee_basis(db, repo, company_id, community_id, actor_id)
    _resolve_house(repo, community_id, command, house_snapshot, lock=lock)
    basis = repo.basis(command.house_id, target_id)
    if original_status not in {"created", "skipped"} or basis is None:
        raise AppError("billing.basis_version_conflict")
    if not matches_fee_basis(command, basis, include_reason=original_status == "created"):
        raise AppError("billing.basis_version_conflict")
    if original_status == "created" and expected_latest_version_no is not None:
        validate_basis_version_number(expected_latest_version_no)
        if basis.version_no != expected_latest_version_no + 1:
            raise AppError("billing.basis_version_conflict")
    if original_status == "skipped" and (
        expected_target_id is not None and basis.id != expected_target_id
    ):
        raise AppError("billing.basis_version_conflict")
    return basis


def create_fee_basis(
    db: Session,
    *,
    company_id: str,
    community_id: str,
    actor_id: str,
    command: FeeBasisCreationCommand,
    expected_latest_version_no: int,
    request_id: str,
    house_snapshot: Mapping[str, Any] | None = None,
    allow_existing: bool = False,
    expected_action: str | None = None,
    expected_target_id: str | None = None,
) -> FeeBasisCreationResult:
    """Authorize and append or skip under the house lock; the caller owns the transaction."""
    validate_basis_version_number(expected_latest_version_no)
    repo = BillingRepository(db, company_id)
    identity, actor = _protect_fee_basis(db, repo, company_id, community_id, actor_id)
    if allow_existing:
        prepared = prepare_fee_basis_creation(
            db,
            company_id=company_id,
            community_id=community_id,
            command=command,
            house_snapshot=house_snapshot,
            expected_latest_version_no=expected_latest_version_no,
            expected_action=expected_action,
            expected_target_id=expected_target_id,
            lock=True,
        )
        if prepared["action"] == "skip":
            basis = repo.basis(command.house_id, prepared["target_id"])
            assert basis is not None
            return FeeBasisCreationResult("skipped", basis)
    else:
        _resolve_house(repo, community_id, command, house_snapshot, lock=True, exclusive=True)
        if repo.latest_basis_number(command.house_id) != expected_latest_version_no:
            raise AppError("billing.basis_version_conflict")
    if expected_latest_version_no >= MAX_CENTS:
        raise AppError("billing.basis_version_conflict")
    basis = FeeBasisVersion(
        id=new_id(),
        house_id=command.house_id,
        version_no=expected_latest_version_no + 1,
        effective_from_month=month_date(command.effective_from_month),
        house_usage=command.house_usage,
        area_sqm=Decimal(command.area_sqm) if command.area_sqm is not None else None,
        unit_price_cents=command.unit_price_cents,
        fixed_amount_cents=command.fixed_amount_cents,
        change_reason=command.change_reason,
        created_by=actor.id,
        created_at=utc_now(),
    )
    db.add(basis)
    identity.audit.record(
        actor=actor,
        action="property.fee_basis.create",
        target_type="fee_basis_version",
        target_id=basis.id,
        request_id=request_id,
        metadata={
            "house_id": command.house_id,
            "version_no": basis.version_no,
            "effective_from_month": command.effective_from_month,
        },
    )
    db.flush()
    return FeeBasisCreationResult("created", basis)
