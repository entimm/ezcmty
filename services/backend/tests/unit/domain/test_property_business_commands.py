from collections.abc import Callable
from datetime import timedelta
from typing import Any, cast

import pytest

from backend_app.core.errors import AppError
from backend_app.domain.billing.calculation import MAX_CENTS, business_today
from backend_app.domain.housing import validate_housing_update
from backend_app.services.property_business.commands import (
    BillReasonAction,
    BillUpdate,
    BindingRevocation,
    ClaimReview,
    FieldChanges,
    ReceiptCorrection,
    ReceiptCreate,
    SpaceCreation,
)


@pytest.mark.parametrize(
    "command",
    [
        lambda: ReceiptCreate(1, 100, business_today() + timedelta(days=1), None, frozenset()),
        lambda: ReceiptCorrection(
            1, 100, business_today() + timedelta(days=1), "纠错", frozenset()
        ),
        lambda: ReceiptCreate(1, 0, None, None, frozenset()),
        lambda: ReceiptCreate(1, True, None, None, frozenset()),
        lambda: ReceiptCorrection(1, MAX_CENTS + 1, None, "纠错", frozenset()),
        lambda: ReceiptCorrection(1, 100, None, "  ", frozenset()),
        lambda: BillReasonAction(1, "", frozenset()),
        lambda: BindingRevocation(1, "  "),
        lambda: ClaimReview(1, cast(Any, "cancelled"), None),
        lambda: ClaimReview(0, "approved", None),
        lambda: BillUpdate(1, FieldChanges({"settled_cents": 100}), frozenset()),
        lambda: SpaceCreation("building", " ", None, None, 0, frozenset()),
        lambda: SpaceCreation("building", "楼栋", None, None, -1, frozenset()),
    ],
)
def test_shared_commands_reject_invalid_business_input_without_http(
    command: Callable[[], object],
) -> None:
    with pytest.raises(AppError) as caught:
        command()
    assert caught.value.code == "VALIDATION_ERROR"


def test_shared_receipt_and_housing_updates_reuse_existing_normalization() -> None:
    receipt = ReceiptCreate(1, 100, business_today(), "  凭据  ", frozenset())
    assert receipt.reason == "凭据" and receipt.received_on == business_today()
    assert validate_housing_update("owner", {"name": " 张三 ", "phone": "+8613800000000"}) == {
        "name": "张三",
        "phone": "13800000000",
    }
    values = {"external_bill_no": " 旧单号 "}
    command = BillUpdate(1, FieldChanges(values), frozenset({"external_bill_no"}))
    values["external_bill_no"] = "后来修改"
    assert command.changes.values == {"external_bill_no": "旧单号"}


@pytest.mark.parametrize(
    "kind, values",
    [
        ("house", {"floor_no": 32768}),
        ("house", {"enabled": "false"}),
        ("owner", {"phone": "123"}),
        ("space", {"node_type": "unit"}),
    ],
)
def test_shared_updates_do_not_depend_on_http_field_validation(
    kind: str, values: dict[str, Any]
) -> None:
    with pytest.raises(AppError):
        validate_housing_update(kind, values)
