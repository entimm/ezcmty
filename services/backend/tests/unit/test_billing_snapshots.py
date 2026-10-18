from copy import deepcopy
from typing import Any

import pytest

from backend_app.schemas.mappers.billing import historical_write_result

IDENTIFIER = "019a1234-1234-7123-8123-123456789abc"
TIMESTAMP = "2026-10-18T16:05:00Z"


@pytest.fixture
def legacy_result() -> dict[str, Any]:
    return {
        "bill": {
            "id": IDENTIFIER,
            "property_company_id": IDENTIFIER,
            "community_id": IDENTIFIER,
            "house_id": IDENTIFIER,
            "bill_type": "property_fee",
            "period_granularity": "month",
            "billing_month": "2026-10",
            "period_start": "2026-10-01",
            "period_end": "2026-11-01",
            "external_bill_no": None,
            "basis_version_id": None,
            "amount_source": "manual",
            "calculation_rule_version": None,
            "receivable_cents": 10000,
            "settled_cents": 3000,
            "outstanding_cents": 7000,
            "lifecycle_status": "active",
            "settlement_status": "partially_settled",
            "due_date": None,
            "is_overdue": False,
            "house_label_snapshot": "春日小区／101",
            "manual_amount_reason": "历史补录",
            "void_reason": None,
            "voided_at": None,
            "voided_by": None,
            "row_version": 1,
            "created_by": IDENTIFIER,
            "created_at": TIMESTAMP,
            "updated_at": TIMESTAMP,
            "basis": None,
            "house_effective_enabled": True,
        },
        "operation": {
            "id": IDENTIFIER,
            "bill_id": IDENTIFIER,
            "action": "receipt",
            "bill_version": 1,
            "actor_id": IDENTIFIER,
            "actor_name": "历史管理员",
            "reason": None,
            "request_id": "historical",
            "created_at": TIMESTAMP,
        },
        "settlement_entries": [
            {
                "id": IDENTIFIER,
                "bill_id": IDENTIFIER,
                "operation_id": IDENTIFIER,
                "entry_type": "receipt",
                "source_type": "offline",
                "amount_cents": 3000,
                "reverses_entry_id": None,
                "reversed_by_entry_id": None,
                "received_on": None,
                "created_at": TIMESTAMP,
                "actor_id": IDENTIFIER,
                "actor_name": "历史管理员",
                "reason": None,
            }
        ],
    }


def test_historical_receipt_result_adds_compatibility_fields_without_rewriting_snapshot(
    legacy_result: dict[str, Any],
) -> None:
    original = deepcopy(legacy_result)
    response = historical_write_result(legacy_result)
    assert response.bill.payment_in_progress is False
    assert response.bill.row_version == 1 and response.bill.settled_cents == 3000
    assert response.operation.actor_type == "admin"
    assert response.operation.actor_id == IDENTIFIER
    assert response.settlement_entries[0].actor_type == "admin"
    assert response.settlement_entries[0].payment_order_item_id is None
    assert legacy_result == original


def test_current_snapshot_fields_are_preserved_by_historical_adapter(
    legacy_result: dict[str, Any],
) -> None:
    legacy_result["bill"]["payment_in_progress"] = True
    legacy_result["operation"].update(
        action="online_receipt", actor_type="system", actor_id=None, actor_name="系统"
    )
    legacy_result["settlement_entries"][0].update(
        source_type="online_payment",
        payment_order_item_id=IDENTIFIER,
        actor_type="system",
        actor_id=None,
        actor_name="系统",
        received_on="2026-10-19",
    )
    response = historical_write_result(legacy_result)
    assert response.bill.payment_in_progress is True
    assert response.operation.actor_type == "system" and response.operation.actor_id is None
    assert response.settlement_entries[0].payment_order_item_id == IDENTIFIER
    assert response.settlement_entries[0].source_type == "online_payment"
