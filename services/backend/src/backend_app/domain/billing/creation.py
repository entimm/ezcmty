"""Shared property-fee creation rules, independent of HTTP and import workflows."""

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, fields
from datetime import date, datetime
from typing import Any, cast

from backend_app.core.errors import AppError
from backend_app.core.identifiers import new_id
from backend_app.domain.billing.calculation import (
    MAX_CENTS,
    RULE_VERSION,
    AmountSource,
    calculate_amount,
    month_date,
    next_month,
    validate_receipt_date,
)
from backend_app.domain.billing.posting import append_receipt
from backend_app.models.billing import Bill, BillSettlementEntry
from backend_app.repositories.billing import BillingRepository


def _invalid() -> AppError:
    return AppError("VALIDATION_ERROR")


def _money(value: object, *, positive: bool = False) -> int:
    if type(value) is not int or not (1 if positive else 0) <= value <= MAX_CENTS:
        raise _invalid()
    return value


def _text(value: object, limit: int, *, required: bool = False) -> str | None:
    if value is not None and not isinstance(value, str):
        raise _invalid()
    value = value.strip() if isinstance(value, str) else ""
    if len(value) > limit or (required and not value):
        raise _invalid()
    return value or None


def _date(value: object) -> date | None:
    if value is None:
        return None
    if type(value) is date:
        return value
    if isinstance(value, str) and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    raise _invalid()


def creation_identity(
    house_id: str, billing_month: str, bill_type: str = "property_fee"
) -> dict[str, str]:
    """Resolve a bill's identity independently of amounts or other creation fields."""
    if not isinstance(house_id, str) or not house_id or bill_type != "property_fee":
        raise _invalid()
    if not isinstance(billing_month, str) or not re.fullmatch(
        r"[0-9]{4}-(0[1-9]|1[0-2])", billing_month
    ):
        raise _invalid()
    try:
        start = month_date(billing_month)
        next_month(start)
    except ValueError, OverflowError:
        raise _invalid() from None
    return {"house_id": house_id, "bill_type": bill_type, "period_start": start.isoformat()}


@dataclass(frozen=True)
class InitialBillReceipt:
    amount_cents: int
    received_on: date | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        _money(self.amount_cents, positive=True)
        received = _date(self.received_on)
        try:
            validate_receipt_date(received)
        except ValueError:
            raise _invalid() from None
        object.__setattr__(self, "received_on", received)
        object.__setattr__(self, "reason", _text(self.reason, 1000))

    def to_dict(self) -> dict[str, Any]:
        return {
            "amount_cents": self.amount_cents,
            "received_on": self.received_on.isoformat() if self.received_on else None,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class BillCreationCommand:
    house_id: str
    billing_month: str
    amount_source: AmountSource
    bill_type: str = "property_fee"
    basis_version_id: str | None = None
    expected_calculation_rule_version: int | None = None
    expected_receivable_cents: int | None = None
    receivable_cents: int | None = None
    manual_amount_reason: str | None = None
    external_bill_no: str | None = None
    due_date: date | None = None
    initial_receipt: InitialBillReceipt | None = None

    def __post_init__(self) -> None:
        creation_identity(self.house_id, self.billing_month, self.bill_type)
        if self.basis_version_id is not None and (
            not isinstance(self.basis_version_id, str) or not self.basis_version_id
        ):
            raise _invalid()
        object.__setattr__(self, "manual_amount_reason", _text(self.manual_amount_reason, 1000))
        object.__setattr__(self, "external_bill_no", _text(self.external_bill_no, 128))
        object.__setattr__(self, "due_date", _date(self.due_date))
        if self.initial_receipt is not None and not isinstance(
            self.initial_receipt, InitialBillReceipt
        ):
            raise _invalid()
        if self.amount_source == "manual":
            _money(self.receivable_cents)
            if self.manual_amount_reason is None or any(
                value is not None
                for value in (
                    self.expected_calculation_rule_version,
                    self.expected_receivable_cents,
                )
            ):
                raise _invalid()
        elif self.amount_source == "basis":
            _money(self.expected_receivable_cents)
            if (
                self.basis_version_id is None
                or type(self.expected_calculation_rule_version) is not int
                or not 1 <= self.expected_calculation_rule_version <= 32767
                or self.receivable_cents is not None
                or self.manual_amount_reason is not None
            ):
                raise _invalid()
        else:
            raise _invalid()

    @classmethod
    def from_input(cls, value: Mapping[str, Any]) -> BillCreationCommand:
        if set(value) - {field.name for field in fields(cls)}:
            raise _invalid()
        data = dict(value)
        initial = data.get("initial_receipt")
        if initial is not None:
            if not isinstance(initial, Mapping) or set(initial) - {
                "amount_cents",
                "received_on",
                "reason",
            }:
                raise _invalid()
            try:
                data["initial_receipt"] = InitialBillReceipt(**initial)
            except TypeError:
                raise _invalid() from None
        try:
            return cls(**data)
        except TypeError:
            raise _invalid() from None

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> BillCreationCommand:
        return cls.from_input(value)

    def to_dict(self) -> dict[str, Any]:
        return {
            **{
                field.name: getattr(self, field.name)
                for field in fields(self)
                if field.name not in {"initial_receipt", "due_date"}
            },
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "initial_receipt": self.initial_receipt.to_dict() if self.initial_receipt else None,
        }


def creation_actions(
    *, initial_paid_cents: int | None = 0, basis_version_id: str | None = None
) -> frozenset[str]:
    """Business capabilities independent of an entry point's permission namespace."""
    actions = {"bill.manage"}
    if basis_version_id is not None:
        actions.add("bill.read")
    if type(initial_paid_cents) is int and initial_paid_cents > 0:
        actions.add("bill_receipt.create")
    return frozenset(actions)


def creation_permissions(
    *, initial_paid_cents: int | None = 0, basis_version_id: str | None = None
) -> frozenset[str]:
    """Existing import templates retain their property permission contract."""
    return frozenset(
        f"property.{action}"
        for action in creation_actions(
            initial_paid_cents=initial_paid_cents, basis_version_id=basis_version_id
        )
    )


def creation_natural_key(command: BillCreationCommand) -> dict[str, str]:
    return creation_identity(command.house_id, command.billing_month, command.bill_type)


def creation_content(command: BillCreationCommand) -> dict[str, Any]:
    start = month_date(command.billing_month)
    return {
        **creation_natural_key(command),
        "period_end": next_month(start).isoformat(),
        "amount_source": command.amount_source,
        "basis_version_id": command.basis_version_id,
        "expected_calculation_rule_version": command.expected_calculation_rule_version,
        "expected_receivable_cents": command.expected_receivable_cents,
        "receivable_cents": command.receivable_cents,
        "manual_amount_reason": command.manual_amount_reason,
        "external_bill_no": command.external_bill_no,
        "due_date": command.due_date.isoformat() if command.due_date else None,
        "initial_receipt": command.initial_receipt.to_dict() if command.initial_receipt else None,
    }


def creation_fingerprint(command: BillCreationCommand) -> str:
    return hashlib.sha256(
        json.dumps(
            creation_content(command), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    ).hexdigest()


def _original_command(result: dict[str, Any]) -> BillCreationCommand | None:
    """Derive creation facts from the immutable create result, never today's bill totals."""
    try:
        bill = result["bill"]
        entries = result["settlement_entries"]
        if not isinstance(bill, dict) or not isinstance(entries, list) or len(entries) > 1:
            return None
        initial = None
        if entries:
            entry = entries[0]
            if entry["entry_type"] != "receipt" or entry["source_type"] != "offline":
                return None
            initial = {
                "amount_cents": entry["amount_cents"],
                "received_on": entry["received_on"],
                "reason": entry["reason"],
            }
        source = bill["amount_source"]
        return BillCreationCommand.from_input(
            {
                "house_id": bill["house_id"],
                "bill_type": bill["bill_type"],
                "billing_month": bill["billing_month"],
                "amount_source": source,
                "basis_version_id": bill["basis_version_id"],
                "expected_calculation_rule_version": bill["calculation_rule_version"]
                if source == "basis"
                else None,
                "expected_receivable_cents": bill["receivable_cents"]
                if source == "basis"
                else None,
                "receivable_cents": bill["receivable_cents"] if source == "manual" else None,
                "manual_amount_reason": bill["manual_amount_reason"],
                "external_bill_no": bill["external_bill_no"],
                "due_date": bill["due_date"],
                "initial_receipt": initial,
            }
        )
    except KeyError, TypeError, ValueError, AppError:
        return None


def inspect_existing_creation(
    repo: BillingRepository, community_id: str, command: BillCreationCommand
) -> str | None:
    existing = repo.active_month_bill(
        community_id, command.house_id, month_date(command.billing_month)
    )
    if existing is None:
        return None
    operation = repo.creation_operation(existing.id)
    original = _original_command(operation.result) if operation is not None else None
    if original is None or creation_content(original) != creation_content(command):
        raise AppError("billing.bill_exists")
    return existing.id


def validate_creation(
    repo: BillingRepository, command: BillCreationCommand, house_snapshot: Mapping[str, Any]
) -> tuple[int, str]:
    if house_snapshot["house_id"] != command.house_id:
        raise AppError("property.house_location_changed")
    if not house_snapshot["effective_enabled"]:
        raise AppError("property.housing_disabled")
    start = month_date(command.billing_month)
    basis = (
        repo.basis(command.house_id, command.basis_version_id) if command.basis_version_id else None
    )
    if command.amount_source == "basis":
        effective = repo.effective_basis(command.house_id, start)
        if effective is None:
            raise AppError("billing.basis_missing")
        amount = calculate_amount(
            effective.area_sqm, effective.unit_price_cents, effective.fixed_amount_cents
        )
        if (
            effective.id != command.basis_version_id
            or command.expected_calculation_rule_version != RULE_VERSION
            or command.expected_receivable_cents != amount
        ):
            raise AppError("billing.basis_changed")
    else:
        amount = cast(int, command.receivable_cents)
        if command.basis_version_id and (basis is None or basis.effective_from_month > start):
            raise AppError("billing.invalid_reference")
    if command.initial_receipt and command.initial_receipt.amount_cents > amount:
        raise AppError("billing.overpayment")
    label = "／".join(
        [
            house_snapshot["community_name"],
            *(node["name"] for node in house_snapshot["path"]),
            house_snapshot["room_no"],
        ]
    )
    if len(label) > 512:
        raise AppError("billing.house_label_too_long")
    return amount, label


def create_bill_records(
    repo: BillingRepository,
    command: BillCreationCommand,
    community_id: str,
    actor_id: str,
    operation_id: str,
    amount: int,
    label: str,
    now: datetime,
) -> tuple[Bill, list[BillSettlementEntry]]:
    start = month_date(command.billing_month)
    bill = Bill(
        id=new_id(),
        property_company_id=repo.company_id,
        community_id=community_id,
        house_id=command.house_id,
        bill_type=command.bill_type,
        period_granularity="month",
        period_start=start,
        period_end=next_month(start),
        external_bill_no=command.external_bill_no,
        basis_version_id=command.basis_version_id,
        amount_source=command.amount_source,
        calculation_rule_version=RULE_VERSION if command.amount_source == "basis" else None,
        receivable_cents=amount,
        settled_cents=0,
        lifecycle_status="active",
        due_date=command.due_date,
        house_label_snapshot=label,
        manual_amount_reason=command.manual_amount_reason,
        row_version=1,
        created_by=actor_id,
        created_at=now,
        updated_at=now,
    )
    entries = []
    if command.initial_receipt:
        entries.append(
            append_receipt(
                bill,
                operation_id,
                command.initial_receipt.amount_cents,
                command.initial_receipt.received_on,
            )
        )
    repo.db.add(bill)
    return bill, entries
