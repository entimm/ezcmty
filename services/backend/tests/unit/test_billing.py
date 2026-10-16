from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from backend_app.domain.billing import MAX_CENTS, calculate_amount
from backend_app.models.billing import FeeBasisVersion
from backend_app.schemas.billing import BillCreate, FeeBasisCreate, ReceiptCreate
from backend_app.schemas.mappers.billing import basis_view


@pytest.mark.parametrize(
    ("area", "rate", "fixed", "expected"),
    [
        (None, None, 0, 0),
        (Decimal("88.1234"), 235, None, 20709),
        (Decimal("1.005"), 100, None, 101),
        (Decimal("100"), 300, 1000, 1000),
        (Decimal("100"), 0, None, 0),
    ],
)
def test_property_fee_uses_exact_decimal_and_fixed_precedence(
    area: Decimal | None, rate: int | None, fixed: int | None, expected: int
) -> None:
    assert calculate_amount(area, rate, fixed) == expected


@pytest.mark.parametrize("reason", ["物" * 1000, "🏠" * 1000])
def test_manual_zero_without_basis_and_unicode_reason_boundary(reason: str) -> None:
    item = BillCreate(
        house_id="019a1234-1234-7123-8123-123456789abc",
        billing_month="2026-01",
        amount_source="manual",
        receivable_cents=0,
        manual_amount_reason=f" {reason} ",
        external_bill_no=" 001a ",
    )
    assert item.basis_version_id is None
    assert item.manual_amount_reason == reason
    assert item.external_bill_no == "001a"


@pytest.mark.parametrize("reason", ["", " \n ", "🏠" * 1001])
def test_basis_rejects_missing_or_overlength_reason(reason: str) -> None:
    with pytest.raises(ValidationError):
        FeeBasisCreate(
            expected_latest_version_no=0,
            effective_from_month="2026-01",
            house_usage="residential",
            fixed_amount_cents=0,
            change_reason=reason,
        )


@pytest.mark.parametrize("amount", [-1, 1.5, True, MAX_CENTS + 1])
def test_money_rejects_noninteger_and_unsafe_values(amount: object) -> None:
    with pytest.raises(ValidationError):
        ReceiptCreate.model_validate({"expected_row_version": 1, "amount_cents": amount})


def test_receipt_rejects_future_business_date() -> None:
    with pytest.raises(ValidationError):
        ReceiptCreate(expected_row_version=1, amount_cents=1, received_on=date(9999, 1, 1))


@pytest.mark.parametrize("year", [1, 999, 2026])
def test_basis_response_uses_four_digit_year_on_all_platforms(year: int) -> None:
    item = FeeBasisVersion(
        id="019a1234-1234-7123-8123-123456789abc",
        house_id="019a1234-1234-7123-8123-123456789abd",
        version_no=1,
        effective_from_month=date(year, 1, 1),
        house_usage="residential",
        area_sqm=None,
        unit_price_cents=None,
        fixed_amount_cents=0,
        change_reason="历史",
        created_by="019a1234-1234-7123-8123-123456789abe",
        created_at=datetime(2026, 10, 16, tzinfo=UTC),
    )
    assert basis_view(item).effective_from_month == f"{year:04d}-01"
