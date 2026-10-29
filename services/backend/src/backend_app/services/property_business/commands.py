"""Ordinary business inputs; HTTP validation stays in the entry adapter."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from types import MappingProxyType
from typing import Any, Literal

from backend_app.core.errors import AppError
from backend_app.core.identifiers import normalize_uuid
from backend_app.domain.billing.calculation import MAX_CENTS, clean_optional
from backend_app.domain.billing.creation import InitialBillReceipt
from backend_app.domain.housing import SpaceType


@dataclass(frozen=True)
class FieldChanges:
    values: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "values", MappingProxyType(dict(self.values)))

    @property
    def fields(self) -> frozenset[str]:
        return frozenset(self.values)


@dataclass(frozen=True)
class SpaceCreation:
    node_type: SpaceType
    name: str
    parent_id: str | None
    external_code: str | None
    sort_order: int
    input_fields: frozenset[str]

    def __post_init__(self) -> None:
        if self.node_type not in ("phase", "building", "unit"):
            raise AppError("VALIDATION_ERROR")
        if self.parent_id is not None:
            try:
                if not isinstance(self.parent_id, str):
                    raise ValueError
                object.__setattr__(self, "parent_id", normalize_uuid(self.parent_id))
            except ValueError:
                raise AppError("VALIDATION_ERROR") from None
        object.__setattr__(self, "name", _text(self.name, 80, required=True))
        object.__setattr__(self, "external_code", _text(self.external_code, 64))
        if type(self.sort_order) is not int or not 0 <= self.sort_order <= 2147483647:
            raise AppError("VALIDATION_ERROR")


@dataclass(frozen=True)
class BillUpdate:
    expected_row_version: int
    changes: FieldChanges
    input_fields: frozenset[str]

    def __post_init__(self) -> None:
        _version(self.expected_row_version)
        require_fields(self.changes, frozenset({"external_bill_no", "due_date"}))
        values = dict(self.changes.values)
        if "external_bill_no" in values:
            values["external_bill_no"] = _text(values["external_bill_no"], 128)
        if values.get("due_date") is not None and type(values["due_date"]) is not date:
            raise AppError("VALIDATION_ERROR")
        object.__setattr__(self, "changes", FieldChanges(values))


@dataclass(frozen=True)
class ReceiptCreate:
    expected_row_version: int
    amount_cents: int
    received_on: date | None
    reason: str | None
    input_fields: frozenset[str]

    def __post_init__(self) -> None:
        _version(self.expected_row_version)
        receipt = InitialBillReceipt(self.amount_cents, self.received_on, self.reason)
        object.__setattr__(self, "received_on", receipt.received_on)
        object.__setattr__(self, "reason", receipt.reason)


@dataclass(frozen=True)
class ReceiptCorrection:
    expected_row_version: int
    corrected_amount_cents: int
    corrected_received_on: date | None
    reason: str
    input_fields: frozenset[str]

    def __post_init__(self) -> None:
        _version(self.expected_row_version)
        receipt = InitialBillReceipt(
            self.corrected_amount_cents, self.corrected_received_on, self.reason
        )
        object.__setattr__(self, "corrected_received_on", receipt.received_on)
        object.__setattr__(self, "reason", _text(receipt.reason, 1000, required=True))


@dataclass(frozen=True)
class BillReasonAction:
    expected_row_version: int
    reason: str
    input_fields: frozenset[str]

    def __post_init__(self) -> None:
        _version(self.expected_row_version)
        object.__setattr__(self, "reason", _text(self.reason, 1000, required=True))


BillMutation = BillUpdate | ReceiptCreate | ReceiptCorrection | BillReasonAction


@dataclass(frozen=True)
class ClaimReview:
    expected_row_version: int
    decision: Literal["approved", "rejected"]
    reason: str | None

    def __post_init__(self) -> None:
        _version(self.expected_row_version)
        if self.decision not in ("approved", "rejected"):
            raise AppError("VALIDATION_ERROR")
        object.__setattr__(self, "reason", _text(self.reason, 1000))


@dataclass(frozen=True)
class BindingRevocation:
    expected_row_version: int
    reason: str

    def __post_init__(self) -> None:
        _version(self.expected_row_version)
        object.__setattr__(self, "reason", _text(self.reason, 1000, required=True))


def require_fields(changes: FieldChanges, allowed: frozenset[str]) -> None:
    if not changes.fields or not changes.fields <= allowed:
        raise AppError("VALIDATION_ERROR")


def _version(value: int) -> None:
    if type(value) is not int or not 1 <= value <= MAX_CENTS:
        raise AppError("VALIDATION_ERROR")


def _text(value: object, limit: int, *, required: bool = False) -> str | None:
    value = clean_optional(value)
    if value is not None and not isinstance(value, str):
        raise AppError("VALIDATION_ERROR")
    if (required and not value) or (isinstance(value, str) and len(value) > limit):
        raise AppError("VALIDATION_ERROR")
    return value
