"""Validated fee-basis inputs and immutable-version comparison rules."""

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass, fields
from decimal import Decimal
from typing import Any, cast

from backend_app.core.errors import AppError
from backend_app.domain.billing.calculation import (
    MAX_CENTS,
    HouseUsage,
    calculate_amount,
    month_date,
    next_month,
)
from backend_app.models.billing import FeeBasisVersion

BASIS_CONTENT_FIELDS = ("house_usage", "area_sqm", "unit_price_cents", "fixed_amount_cents")


def _invalid() -> AppError:
    return AppError("VALIDATION_ERROR")


def validate_basis_version_number(value: object) -> int:
    if type(value) is not int or not 0 <= value <= MAX_CENTS:
        raise _invalid()
    return value


@dataclass(frozen=True, kw_only=True)
class FeeBasisCreationCommand:
    house_id: str
    effective_from_month: str
    house_usage: HouseUsage
    change_reason: str
    area_sqm: str | None = None
    unit_price_cents: int | None = None
    fixed_amount_cents: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.house_id, str) or not self.house_id.strip():
            raise _invalid()
        if not isinstance(self.effective_from_month, str) or not re.fullmatch(
            r"[0-9]{4}-(0[1-9]|1[0-2])", self.effective_from_month
        ):
            raise _invalid()
        try:
            next_month(month_date(self.effective_from_month))
        except ValueError, OverflowError:
            raise _invalid() from None
        if self.house_usage not in ("residential", "commercial", "office", "other"):
            raise _invalid()
        if not isinstance(self.change_reason, str):
            raise _invalid()
        reason = self.change_reason.strip()
        if not reason or len(reason) > 1000:
            raise _invalid()
        object.__setattr__(self, "change_reason", reason)
        area = None
        if self.area_sqm is not None:
            if not isinstance(self.area_sqm, str) or not re.fullmatch(
                r"(?:0|[1-9]\d{0,7})(?:\.\d{1,4})?", self.area_sqm
            ):
                raise _invalid()
            area = Decimal(self.area_sqm)
            if area <= 0:
                raise _invalid()
            object.__setattr__(self, "area_sqm", format(area.normalize(), "f"))
        for value in (self.unit_price_cents, self.fixed_amount_cents):
            if value is not None and (type(value) is not int or not 0 <= value <= MAX_CENTS):
                raise _invalid()
        try:
            calculate_amount(area, self.unit_price_cents, self.fixed_amount_cents)
        except ValueError:
            raise _invalid() from None

    @classmethod
    def from_input(cls, value: Mapping[str, Any]) -> FeeBasisCreationCommand:
        if set(value) - {field.name for field in fields(cls)}:
            raise _invalid()
        try:
            return cls(**value)
        except TypeError:
            raise _invalid() from None

    @classmethod
    def from_basis(cls, value: FeeBasisVersion) -> FeeBasisCreationCommand:
        return cls(
            house_id=value.house_id,
            effective_from_month=(
                f"{value.effective_from_month.year:04d}-{value.effective_from_month.month:02d}"
            ),
            house_usage=cast(HouseUsage, value.house_usage),
            area_sqm=format(value.area_sqm, "f") if value.area_sqm is not None else None,
            unit_price_cents=value.unit_price_cents,
            fixed_amount_cents=value.fixed_amount_cents,
            change_reason=value.change_reason,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def calculated_amount(self) -> int:
        return calculate_amount(
            Decimal(self.area_sqm) if self.area_sqm is not None else None,
            self.unit_price_cents,
            self.fixed_amount_cents,
        )


def matches_fee_basis(
    command: FeeBasisCreationCommand, basis: FeeBasisVersion, *, include_reason: bool = False
) -> bool:
    original = FeeBasisCreationCommand.from_basis(basis).to_dict()
    proposed = command.to_dict()
    if not include_reason:
        original.pop("change_reason")
        proposed.pop("change_reason")
    return original == proposed


def fee_basis_fingerprint(
    command: FeeBasisCreationCommand,
    house_snapshot: Mapping[str, Any],
    expected_latest_version_no: int,
) -> str:
    """Identify the submitted facts and baseline, excluding derived preview/state values."""
    validate_basis_version_number(expected_latest_version_no)
    location = {
        key: house_snapshot[key]
        for key in ("house_id", "community_id", "space_node_id", "room_no", "house_external_code")
    }
    location["path"] = [
        {key: node[key] for key in ("id", "node_type", "name")} for node in house_snapshot["path"]
    ]
    payload = {
        "command": command.to_dict(),
        "house_location": location,
        "expected_latest_version_no": expected_latest_version_no,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
