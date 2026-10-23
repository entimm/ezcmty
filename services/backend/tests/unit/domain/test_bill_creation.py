from datetime import date
from typing import Any

import pytest
from pydantic import ValidationError

from backend_app.core.errors import AppError
from backend_app.domain.billing import MAX_CENTS
from backend_app.domain.billing.creation import (
    BillCreationCommand,
    creation_content,
    creation_fingerprint,
    creation_identity,
    creation_permissions,
)
from backend_app.schemas.billing import BillCreate


def test_command_round_trip_normalizes_creation_facts_without_protocol_types() -> None:
    command = BillCreationCommand.from_input(
        {
            "house_id": "house",
            "billing_month": "2024-01",
            "amount_source": "manual",
            "receivable_cents": 30000,
            "manual_amount_reason": " 迁账 ",
            "external_bill_no": " 001a ",
            "due_date": "2024-02-01",
            "initial_receipt": {"amount_cents": 10000, "received_on": None, "reason": " 累计迁入 "},
        }
    )
    assert command.due_date == date(2024, 2, 1)
    assert command.manual_amount_reason == "迁账"
    assert command.external_bill_no == "001a"
    assert command.initial_receipt and command.initial_receipt.reason == "累计迁入"
    restored = BillCreationCommand.from_dict(command.to_dict())
    assert restored == command
    assert creation_fingerprint(restored) == creation_fingerprint(command)
    content = creation_content(command)
    assert content["period_start"] == "2024-01-01"
    assert content["period_end"] == "2024-02-01"
    assert content["initial_receipt"]["received_on"] is None
    assert set(content).isdisjoint({"actor_id", "house_label_snapshot", "settled_cents"})


@pytest.mark.parametrize(
    "changes",
    [
        {"billing_month": "2024-13"},
        {"billing_month": "9999-12"},
        {"receivable_cents": -1},
        {"receivable_cents": True},
        {"receivable_cents": MAX_CENTS + 1},
        {"manual_amount_reason": "  "},
        {"manual_amount_reason": "🏠" * 1001},
        {"external_bill_no": "x" * 129},
        {"due_date": "20240101"},
        {"initial_receipt": {"amount_cents": 0}},
        {"initial_receipt": {"amount_cents": 1, "received_on": "9999-01-01"}},
        {"expected_receivable_cents": 100},
        {"amount_source": "basis"},
    ],
)
def test_commands_enforce_business_boundaries_without_http_validation(
    changes: dict[str, Any],
) -> None:
    values: dict[str, Any] = {
        "house_id": "house",
        "billing_month": "2024-01",
        "amount_source": "manual",
        "receivable_cents": 10000,
        "manual_amount_reason": "迁账",
    }
    with pytest.raises(AppError) as caught:
        BillCreationCommand.from_input({**values, **changes})
    assert caught.value.code == "VALIDATION_ERROR"


@pytest.mark.parametrize("paid", [0, 1, MAX_CENTS])
def test_receipt_permission_is_independent_of_unrelated_command_fields(paid: int) -> None:
    needed = creation_permissions(initial_paid_cents=paid)
    assert "property.bill.create" in needed
    assert ("property.bill_receipt.create" in needed) is (paid > 0)
    assert "property.fee_basis.read" in creation_permissions(
        initial_paid_cents=paid, basis_version_id="reference"
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"expected_receivable_cents": 10000},
        {"manual_amount_reason": None},
        {"initial_receipt": {"amount_cents": 1, "received_on": "9999-01-01"}},
    ],
)
def test_http_entry_translates_shared_creation_validation_to_pydantic_errors(
    changes: dict[str, Any],
) -> None:
    data: dict[str, Any] = {
        "house_id": "019a1234-1234-7123-8123-123456789abc",
        "billing_month": "2024-01",
        "amount_source": "manual",
        "receivable_cents": 10000,
        "manual_amount_reason": "历史",
        **changes,
    }
    with pytest.raises(AppError) as caught:
        BillCreationCommand.from_input(data)
    assert caught.value.code == "VALIDATION_ERROR"
    with pytest.raises(ValidationError):
        BillCreate.model_validate(data)


def test_creation_identity_remains_available_when_amount_fields_are_invalid() -> None:
    assert creation_identity("house", "2024-01") == {
        "house_id": "house",
        "bill_type": "property_fee",
        "period_start": "2024-01-01",
    }
    with pytest.raises(AppError) as caught:
        BillCreationCommand.from_input(
            {
                "house_id": "house",
                "billing_month": "2024-01",
                "amount_source": "manual",
                "receivable_cents": "bad",
                "manual_amount_reason": "历史",
            }
        )
    assert caught.value.code == "VALIDATION_ERROR"


@pytest.mark.parametrize("month", ["2024-13", "2024-1", "0000-01", "9999-12"])
def test_partial_identity_uses_the_same_month_boundary_as_creation(month: str) -> None:
    with pytest.raises(AppError) as caught:
        creation_identity("house", month)
    assert caught.value.code == "VALIDATION_ERROR"
