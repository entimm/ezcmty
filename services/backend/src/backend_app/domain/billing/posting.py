"""Append verified receipts inside the caller's locked billing transaction."""

import hashlib
import json
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Literal
from zoneinfo import ZoneInfo

from backend_app.core.identifiers import new_id
from backend_app.models.admin import utc_now
from backend_app.models.billing import Bill, BillOperation, BillSettlementEntry
from backend_app.repositories.billing import BillingRepository

if TYPE_CHECKING:
    from backend_app.models.payments import PaymentOrderItem


def append_receipt(
    bill: Bill,
    operation_id: str,
    amount_cents: int,
    received_on: date | None,
    *,
    source_type: Literal["offline", "online_payment"] = "offline",
    payment_order_item_id: str | None = None,
) -> BillSettlementEntry:
    """Apply a positive receipt; the caller owns operations, versions and persistence."""
    if bill.lifecycle_status != "active" or amount_cents <= 0:
        raise ValueError("Receipt requires an active bill and a positive amount")
    if bill.settled_cents + amount_cents > bill.receivable_cents:
        raise ValueError("Receipt exceeds the bill's remaining amount")
    if (source_type == "online_payment") != (payment_order_item_id is not None):
        raise ValueError("Online receipt requires its payment item")
    if source_type == "online_payment" and received_on is None:
        raise ValueError("Online receipt requires a verified business date")
    bill.settled_cents += amount_cents
    bill.updated_at = utc_now()
    return BillSettlementEntry(
        id=new_id(),
        bill_id=bill.id,
        operation_id=operation_id,
        entry_type="receipt",
        source_type=source_type,
        payment_order_item_id=payment_order_item_id,
        amount_cents=amount_cents,
        received_on=received_on,
        reverses_entry_id=None,
        created_at=utc_now(),
    )


def post_online_receipt(
    repo: BillingRepository,
    bill: Bill,
    payment_item: PaymentOrderItem,
    paid_at: datetime,
    request_id: str,
) -> BillOperation:
    """Post one immutable payment item without a session identity or a commit."""
    if paid_at.tzinfo is None or paid_at.utcoffset() is None:
        raise ValueError("Verified payment time must have a timezone")
    if payment_item.bill_id != bill.id or payment_item.property_company_id != repo.company_id:
        raise ValueError("Payment item does not belong to the locked bill")
    stable_input = [
        payment_item.id,
        bill.id,
        payment_item.amount_cents,
        paid_at.astimezone(UTC).isoformat(),
    ]
    fingerprint = hashlib.sha256(
        json.dumps(stable_input, separators=(",", ":")).encode()
    ).hexdigest()
    key = f"online_receipt_{payment_item.id}"
    previous = repo.operation_by_key(key)
    if previous is not None:
        if previous.request_fingerprint != fingerprint or previous.actor_type != "system":
            raise ValueError("Conflicting online receipt evidence")
        return previous
    operation_id = new_id()
    entry = append_receipt(
        bill,
        operation_id,
        payment_item.amount_cents,
        paid_at.astimezone(ZoneInfo("Asia/Shanghai")).date(),
        source_type="online_payment",
        payment_order_item_id=payment_item.id,
    )
    bill.row_version += 1
    operation = BillOperation(
        id=operation_id,
        property_company_id=repo.company_id,
        bill_id=bill.id,
        bill_version=bill.row_version,
        action="online_receipt",
        idempotency_key=key,
        request_fingerprint=fingerprint,
        result={
            "bill_id": bill.id,
            "bill_version": bill.row_version,
            "settlement_entry_id": entry.id,
            "payment_order_item_id": payment_item.id,
            "amount_cents": payment_item.amount_cents,
        },
        response_status=None,
        reason=None,
        actor_type="system",
        actor_id=None,
        request_id=request_id,
        created_at=utc_now(),
    )
    repo.add_receipt(operation, entry)
    return operation
