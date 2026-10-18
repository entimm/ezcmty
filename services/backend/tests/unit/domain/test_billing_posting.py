from datetime import UTC, date, datetime, timedelta, timezone
from unittest.mock import Mock

import pytest
from sqlalchemy.orm import Session

from backend_app.core.identifiers import new_id
from backend_app.domain.billing.posting import append_receipt, post_online_receipt
from backend_app.models.billing import Bill, BillSettlementEntry
from backend_app.models.payments import PaymentOrderItem
from backend_app.repositories.billing import BillingRepository
from backend_app.schemas.mappers.billing import entry_view, operation_view


@pytest.fixture
def bill() -> Bill:
    return Bill(
        id=new_id(),
        property_company_id=new_id(),
        lifecycle_status="active",
        receivable_cents=10000,
        settled_cents=3000,
        row_version=2,
        updated_at=datetime(2026, 10, 18, tzinfo=UTC),
    )


@pytest.fixture
def payment_item(bill: Bill) -> PaymentOrderItem:
    return PaymentOrderItem(
        id=new_id(),
        property_company_id=bill.property_company_id,
        payment_order_id=new_id(),
        bill_id=bill.id,
        amount_cents=7000,
    )


def test_append_offline_receipt_uses_caller_operation_and_preserves_caller_version(
    bill: Bill,
) -> None:
    operation_id = new_id()
    receipt = append_receipt(bill, operation_id, 1200, None)
    assert bill.settled_cents == 4200
    assert bill.row_version == 2
    assert receipt.bill_id == bill.id
    assert receipt.operation_id == operation_id
    assert receipt.source_type == "offline" and receipt.payment_order_item_id is None
    assert receipt.amount_cents == 1200 and receipt.received_on is None
    assert receipt.reverses_entry_id is None and receipt.entry_type == "receipt"


@pytest.mark.parametrize(
    ("state", "amount"),
    [("voided", 100), ("active", 0), ("active", -1), ("active", 7001)],
    ids=["voided", "zero", "negative", "overpayment"],
)
def test_append_rejects_invalid_receipt_without_changing_balance(
    bill: Bill, state: str, amount: int
) -> None:
    bill.lifecycle_status = state
    with pytest.raises(ValueError):
        append_receipt(bill, new_id(), amount, None)
    assert (bill.settled_cents, bill.row_version) == (3000, 2)


@pytest.mark.parametrize("invalid", ["missing_item", "offline_item", "missing_date"])
def test_append_rejects_inconsistent_online_source(bill: Bill, invalid: str) -> None:
    with pytest.raises(ValueError):
        append_receipt(
            bill,
            new_id(),
            100,
            None if invalid == "missing_date" else date(2026, 10, 19),
            source_type="offline" if invalid == "offline_item" else "online_payment",
            payment_order_item_id=None if invalid == "missing_item" else new_id(),
        )
    assert bill.settled_cents == 3000


def test_post_online_receipt_has_system_projection_and_shanghai_business_date(
    bill: Bill, payment_item: PaymentOrderItem
) -> None:
    db = Mock(spec=Session)
    db.scalar.return_value = None
    operation = post_online_receipt(
        BillingRepository(db, bill.property_company_id),
        bill,
        payment_item,
        datetime(2026, 10, 18, 16, 5, tzinfo=UTC),
        "confirmation",
    )
    receipt = next(
        call.args[0]
        for call in db.add.call_args_list
        if isinstance(call.args[0], BillSettlementEntry)
    )
    assert (bill.settled_cents, bill.row_version) == (10000, 3)
    assert operation.idempotency_key == f"online_receipt_{payment_item.id}"
    assert operation.actor_type == "system" and operation.actor_id is None
    assert operation.action == "online_receipt" and operation.response_status is None
    assert receipt.payment_order_item_id == payment_item.id
    assert receipt.source_type == "online_payment"
    assert receipt.received_on == date(2026, 10, 19)
    operation_response = operation_view(operation, "系统")
    entry_response = entry_view(receipt, operation, "系统")
    assert operation_response.actor_id is None and operation_response.actor_name == "系统"
    assert entry_response.actor_type == "system" and entry_response.actor_id is None
    assert entry_response.payment_order_item_id == payment_item.id
    assert entry_response.amount_cents == payment_item.amount_cents
    db.commit.assert_not_called()


def test_online_replay_accepts_the_same_instant_in_another_timezone(
    bill: Bill, payment_item: PaymentOrderItem
) -> None:
    db = Mock(spec=Session)
    db.scalar.return_value = None
    repo = BillingRepository(db, bill.property_company_id)
    paid_at = datetime(2026, 10, 18, 16, 5, tzinfo=UTC)
    first = post_online_receipt(repo, bill, payment_item, paid_at, "first-evidence")
    db.scalar.return_value = first
    replay = post_online_receipt(
        repo,
        bill,
        payment_item,
        paid_at.astimezone(timezone(timedelta(hours=8))),
        "query-evidence",
    )
    assert replay is first
    assert (bill.settled_cents, bill.row_version) == (10000, 3)
    assert len(db.add.call_args_list) == 2
    db.commit.assert_not_called()


def test_online_replay_rejects_different_success_evidence(
    bill: Bill, payment_item: PaymentOrderItem
) -> None:
    db = Mock(spec=Session)
    db.scalar.return_value = None
    repo = BillingRepository(db, bill.property_company_id)
    paid_at = datetime(2026, 10, 18, 16, 5, tzinfo=UTC)
    first = post_online_receipt(repo, bill, payment_item, paid_at, "first-evidence")
    db.scalar.return_value = first
    with pytest.raises(ValueError, match="Conflicting online receipt evidence"):
        post_online_receipt(repo, bill, payment_item, paid_at + timedelta(seconds=1), "query")
    assert (bill.settled_cents, bill.row_version) == (10000, 3)


@pytest.mark.parametrize("invalid", ["bill", "company", "naive_time"])
def test_online_posting_rejects_unrelated_items_or_unzoned_payment_time(
    bill: Bill, payment_item: PaymentOrderItem, invalid: str
) -> None:
    db = Mock(spec=Session)
    db.scalar.return_value = None
    if invalid == "bill":
        payment_item.bill_id = new_id()
    if invalid == "company":
        payment_item.property_company_id = new_id()
    paid_at = datetime(2026, 10, 19, tzinfo=None if invalid == "naive_time" else UTC)
    with pytest.raises(ValueError):
        post_online_receipt(
            BillingRepository(db, bill.property_company_id), bill, payment_item, paid_at, "request"
        )
    assert (bill.settled_cents, bill.row_version) == (3000, 2)
    db.add.assert_not_called()
    db.commit.assert_not_called()
