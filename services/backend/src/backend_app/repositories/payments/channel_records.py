import json
import re
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from backend_app.core.identifiers import new_id
from backend_app.models.payments import PaymentChannelNotification, PaymentChannelRequest
from backend_app.repositories.payments.tasks import TaskLease, ensure_task, require_current_lease

REQUEST_TARGETS = {
    "payment_submit": "payment_order_id",
    "payment_query": "payment_order_id",
    "payment_close": "payment_order_id",
    "remaining_amount": "payment_order_id",
    "profit_sharing_submit": "profit_sharing_order_id",
    "profit_sharing_query": "profit_sharing_order_id",
    "unfreeze_submit": "unfreeze_order_id",
    "unfreeze_query": "unfreeze_order_id",
    "receiver_add": "merchant_binding_id",
    "receiver_delete": "merchant_binding_id",
    "maximum_ratio": "merchant_binding_id",
    "trade_statement": "reconciliation_run_id",
    "profit_sharing_statement": "reconciliation_run_id",
    "platform_fundflow_statement": "reconciliation_run_id",
    "statement_download": "reconciliation_run_id",
}

# Ordinary diagnostics never contain raw channel payloads, payer identifiers or credentials.
_SNAPSHOT_FIELDS = frozenset(
    {
        "service_provider_merchant_no",
        "merchant_no",
        "app_id",
        "order_no",
        "amount_cents",
        "expires_at",
        "payer_identity_digest",
        "channel_transaction_no",
        "payer_total_cents",
        "currency",
        "paid_at",
        "channel_status",
        "prepay_available",
        "receiver_type",
        "receiver_account",
        "relation_type",
        "receivers",
        "unfreeze_unsplit",
        "channel_order_no",
        "channel_detail_no",
        "finished_at",
        "error_code",
        "maximum_ratio_bps",
        "remaining_cents",
        "business_date",
        "statement_type",
        "hash_type",
        "source_digest",
        "source_request_id",
        "source_row_count",
        "summary",
        "channel_fee_cents",
        "matched_count",
        "difference_count",
        "unclassified_count",
        "company_summaries",
        "property_company_id",
        "check_code",
        "reference_key",
        "difference_type",
        "expected_cents",
        "actual_cents",
        "detected_at",
        "decisions",
        "status",
        "unapplied_reason",
        "channel_record_no",
        "channel_business_type",
        "channel_business_name",
        "receiver_identity_digest",
        "direction",
        "booked_at",
        "payment_amount_cents",
        "row_count",
        "company_id",
        "matched",
        "different",
        "local_count",
        "channel_count",
        "discrepancy_count",
        "local_amount_cents",
        "channel_amount_cents",
        "source",
        "checked_at",
        "expected_status",
        "actual_status",
        "statement_line_no",
        "evidence",
    }
)


def validate_snapshot(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    def validate(value: object, depth: int = 0, *, company_groups: bool = False) -> None:
        if depth > 12:
            raise ValueError("Channel evidence nesting exceeds its bound")
        if isinstance(value, dict):
            for key, child in value.items():
                if company_groups:
                    if not re.fullmatch(r"[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}", key):
                        raise ValueError("Channel evidence company group key is invalid")
                elif key not in _SNAPSHOT_FIELDS:
                    raise ValueError("Channel evidence contains a field outside the whitelist")
                validate(child, depth + 1, company_groups=key == "company_summaries")
        elif isinstance(value, list):
            if len(value) > 10000:
                raise ValueError("Channel evidence collection exceeds its bound")
            for child in value:
                validate(child, depth + 1)
        elif isinstance(value, str):
            if len(value) > 1000 or "\x00" in value:
                raise ValueError("Channel evidence string exceeds its bound")
        elif value is not None and type(value) not in {int, bool}:
            raise ValueError("Channel evidence must contain plain JSON values")

    result = dict(snapshot)
    validate(result)
    serialized = json.dumps(result, ensure_ascii=False, allow_nan=False)
    if len(serialized.encode()) > 1_048_576:
        raise ValueError("Channel evidence exceeds its bound")
    return result


def start_request(
    db: Session,
    *,
    operation: str,
    target_id: str,
    request_snapshot: Mapping[str, Any],
    request_id: str,
    now: datetime,
) -> PaymentChannelRequest:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", request_id):
        raise ValueError("Invalid diagnostic request identifier")
    record = PaymentChannelRequest(
        operation=operation,
        **{REQUEST_TARGETS[operation]: target_id},
        request_snapshot=validate_snapshot(request_snapshot),
        request_id=request_id,
        outcome="started",
        created_at=now,
    )
    db.add(record)
    db.flush()
    return record


def save_response(
    db: Session,
    request_id: str,
    *,
    outcome: Literal["verified_response", "transport_unknown", "invalid_response"],
    now: datetime,
    response_snapshot: Mapping[str, Any] | None = None,
    http_status: int | None = None,
    channel_request_id: str | None = None,
    error_code: str | None = None,
    seal: bool = True,
) -> PaymentChannelRequest:
    record = db.scalars(
        select(PaymentChannelRequest)
        .where(PaymentChannelRequest.id == request_id)
        .with_for_update(of=PaymentChannelRequest)
    ).one()
    if record.finished_at is not None or record.outcome != "started":
        raise ValueError("Channel attempt result has already been saved")
    if not seal and (record.operation != "statement_download" or outcome != "verified_response"):
        raise ValueError("Only authenticated statement source may remain unsealed")
    if channel_request_id and not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", channel_request_id):
        raise ValueError("Invalid channel request identifier")
    if error_code and not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", error_code):
        raise ValueError("Channel diagnostics must use a bounded error code")
    record.outcome = outcome
    record.http_status = http_status
    record.channel_request_id = channel_request_id
    record.error_code = error_code
    record.response_snapshot = validate_snapshot(response_snapshot) if response_snapshot else None
    record.finished_at = now if seal else None
    db.flush()
    return record


def finish_statement(
    db: Session,
    request_id: str,
    lease: TaskLease,
    *,
    now: datetime,
    decision_snapshot: Mapping[str, Any],
) -> PaymentChannelRequest:
    # Caller already holds the batch/business locks; task is acquired last.
    require_current_lease(db, lease, now=now)
    record = db.scalars(
        select(PaymentChannelRequest)
        .where(PaymentChannelRequest.id == request_id)
        .with_for_update(of=PaymentChannelRequest)
    ).one()
    if (
        record.operation != "statement_download"
        or record.outcome != "verified_response"
        or record.finished_at is not None
    ):
        raise ValueError("Statement source is unavailable for decisions")
    if lease.task_type != "reconciliation" or record.reconciliation_run_id != lease.target_id:
        raise ValueError("Statement task does not own this reconciliation source")
    old = record.response_snapshot or {}
    additions = validate_snapshot(decision_snapshot)
    if old.keys() & additions.keys():
        raise ValueError("Authenticated source evidence cannot be overwritten")
    record.response_snapshot = validate_snapshot(old | additions)
    record.finished_at = now
    db.flush()
    return record


def store_notification(
    db: Session,
    *,
    channel_notification_id: str,
    notification_type: str,
    payload: Mapping[str, Any],
    now: datetime,
) -> tuple[PaymentChannelNotification, bool]:
    safe_payload = validate_snapshot(payload)
    inserted = db.scalar(
        insert(PaymentChannelNotification)
        .values(
            id=new_id(),
            channel_notification_id=channel_notification_id,
            notification_type=notification_type,
            payload=safe_payload,
            status="pending",
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_nothing(index_elements=[PaymentChannelNotification.channel_notification_id])
        .returning(PaymentChannelNotification.id)
    )
    record = db.scalars(
        select(PaymentChannelNotification).where(
            PaymentChannelNotification.channel_notification_id == channel_notification_id
        )
    ).one()
    if record.notification_type != notification_type or record.payload != safe_payload:
        raise ValueError("Channel notification identifier conflicts with existing evidence")
    if inserted is not None:
        ensure_task(db, "notification_process", record.id, now=now)
    return record, inserted is not None
