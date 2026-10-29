"""Transaction-participating creation shared by manual and batch entry points."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy.orm import Session

from backend_app.core.errors import AppError
from backend_app.core.identifiers import new_id
from backend_app.domain.billing import business_today, month_date
from backend_app.domain.billing.creation import (
    BillCreationCommand,
    create_bill_records,
    creation_actions,
    creation_fingerprint,
    creation_natural_key,
    inspect_existing_creation,
    validate_creation,
)
from backend_app.domain.housing import house_location_snapshot, revalidate_house_location
from backend_app.models.admin import utc_now
from backend_app.models.billing import BillOperation
from backend_app.repositories.billing import BillingRepository
from backend_app.schemas import billing as schema
from backend_app.schemas.mappers.billing import (
    bill_view,
    entry_view,
    historical_write_result,
    operation_view,
)
from backend_app.services.property_business.context import PropertyBusinessContext


@dataclass(frozen=True)
class BillCreationResult:
    status: Literal["created", "skipped"]
    bill_id: str
    operation_id: str | None
    result: dict[str, Any]


def prepare_bill_creation(
    db: Session,
    *,
    company_id: str,
    community_id: str,
    command: BillCreationCommand,
    house_snapshot: Mapping[str, Any] | None = None,
    target_id: str | None = None,
) -> dict[str, Any]:
    """Read current business facts without writing or changing a prepared command."""
    repo = BillingRepository(db, company_id)
    resolved = (
        revalidate_house_location(repo.housing, community_id, house_snapshot)
        if house_snapshot is not None
        else house_location_snapshot(repo.housing, community_id, command.house_id)
    )
    if target_id is not None:
        target = repo.bill(community_id, target_id)
        if target is None:
            raise AppError("resource.not_found")
        if target.lifecycle_status != "active":
            raise AppError("billing.bill_voided")
        if target.house_id != command.house_id:
            raise AppError("billing.bill_exists")
    amount, label = validate_creation(repo, command, resolved)
    existing_id = inspect_existing_creation(repo, community_id, command)
    if target_id is not None and existing_id != target_id:
        raise AppError("billing.bill_exists")
    paid = command.initial_receipt.amount_cents if command.initial_receipt else 0
    return {
        "action": "skip" if existing_id else "create",
        "target_id": existing_id,
        "natural_key": creation_natural_key(command),
        "input_fingerprint": creation_fingerprint(command),
        "house_label_snapshot": label,
        "receivable_cents": amount,
        "initial_paid_cents": paid,
        "outstanding_cents": amount - paid,
    }


def create_bill(
    db: Session,
    *,
    company_id: str,
    community_id: str,
    actor_id: str,
    context: PropertyBusinessContext,
    command: BillCreationCommand,
    key: str,
    fingerprint: str,
    request_id: str,
    input_fields: frozenset[str],
    house_snapshot: Mapping[str, Any] | None = None,
    allow_existing: bool = False,
    expected_target_id: str | None = None,
) -> BillCreationResult:
    """Apply one authorized creation; the caller owns commit, rollback and retry."""
    repo = BillingRepository(db, company_id)
    if context.company_id != company_id or context.actor_id != actor_id:
        raise AppError("auth.forbidden")
    needed = creation_actions(
        initial_paid_cents=command.initial_receipt.amount_cents if command.initial_receipt else 0,
        basis_version_id=command.basis_version_id,
    )
    actor = context.require(*needed, lock=True, shared=True)
    if repo.community(community_id, lock=True) is None:
        raise AppError("resource.not_found")

    def replay() -> BillCreationResult | None:
        previous = repo.operation_by_key(key)
        if previous is None:
            return None
        if (
            previous.request_fingerprint != fingerprint
            or previous.actor_type != "admin"
            or previous.action != "create"
            or (not allow_existing and previous.actor_id != actor_id)
            or (expected_target_id is not None and previous.bill_id != expected_target_id)
        ):
            raise AppError("billing.idempotency_conflict")
        if allow_existing:
            prepare_bill_creation(
                db,
                company_id=company_id,
                community_id=community_id,
                command=command,
                house_snapshot=house_snapshot,
                target_id=previous.bill_id,
            )
        return BillCreationResult(
            "skipped",
            previous.bill_id,
            previous.id,
            historical_write_result(previous.result).model_dump(mode="json"),
        )

    # Retain first-result replay before applying conditions required only for a new write.
    if expected_target_id is None:
        previous_result = replay()
        if previous_result is not None:
            return previous_result
    resolved = (
        revalidate_house_location(
            repo.housing, community_id, house_snapshot, lock=True, exclusive=True
        )
        if house_snapshot is not None
        else house_location_snapshot(
            repo.housing, community_id, command.house_id, lock=True, exclusive=True
        )
    )
    if expected_target_id is not None:
        target = repo.bill(community_id, expected_target_id, lock=True)
        if target is None:
            raise AppError("resource.not_found")
        if target.lifecycle_status != "active":
            raise AppError("billing.bill_voided")
        if target.house_id != command.house_id:
            raise AppError("billing.bill_exists")
    previous_result = replay()
    if previous_result is not None:
        return previous_result
    amount, label = validate_creation(repo, command, resolved)
    if allow_existing or expected_target_id is not None:
        existing_id = inspect_existing_creation(repo, community_id, command)
        if expected_target_id is not None and existing_id != expected_target_id:
            raise AppError("billing.bill_exists")
        if existing_id is not None:
            existing_operation = repo.creation_operation(existing_id)
            assert existing_operation is not None
            return BillCreationResult(
                "skipped",
                existing_id,
                existing_operation.id,
                historical_write_result(existing_operation.result).model_dump(mode="json"),
            )
    elif (
        repo.active_month_bill(community_id, command.house_id, month_date(command.billing_month))
        is not None
    ):
        raise AppError("billing.bill_exists")

    now = utc_now()
    operation_id = new_id()
    bill, entries = create_bill_records(
        repo, command, community_id, actor.id, operation_id, amount, label, now
    )
    db.flush()
    db.refresh(bill)
    operation = BillOperation(
        id=operation_id,
        property_company_id=company_id,
        bill_id=bill.id,
        bill_version=1,
        action="create",
        idempotency_key=key,
        request_fingerprint=fingerprint,
        result={},
        response_status=201,
        reason=command.initial_receipt.reason if command.initial_receipt else None,
        actor_type="admin",
        actor_id=actor.id,
        request_id=request_id,
        created_at=now,
    )
    basis = (
        repo.basis(command.house_id, command.basis_version_id) if command.basis_version_id else None
    )
    result = schema.BillWriteResult(
        bill=bill_view(bill, basis, resolved["effective_enabled"], business_today()),
        operation=operation_view(operation, actor.display_name),
        settlement_entries=[entry_view(entry, operation, actor.display_name) for entry in entries],
    )
    operation.result = result.model_dump(mode="json")
    db.add(operation)
    db.flush()
    db.add_all(entries)
    context.record(
        actor=actor,
        action="property.bill.create",
        target_type="bill",
        target_id=bill.id,
        request_id=request_id,
        metadata={
            "operation_id": operation_id,
            "bill_version": 1,
            "settlement_entry_ids": [entry.id for entry in entries],
            "changed_fields": sorted(input_fields),
        },
    )
    return BillCreationResult("created", bill.id, operation.id, result.model_dump(mode="json"))
