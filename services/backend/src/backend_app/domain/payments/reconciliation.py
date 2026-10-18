import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

BUSINESS_ZONE = ZoneInfo("Asia/Shanghai")
SUMMARY_FIELDS = (
    "local_count",
    "channel_count",
    "matched_count",
    "discrepancy_count",
    "local_amount_cents",
    "channel_amount_cents",
    "channel_fee_cents",
)


def business_date(value: datetime | str) -> date:
    parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
    if parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=BUSINESS_ZONE)
    return parsed.astimezone(BUSINESS_ZONE).date()


def reference_key(check_code: str, *identity: str) -> str:
    digest = hashlib.sha256(
        json.dumps(identity, ensure_ascii=True, separators=(",", ":")).encode()
    ).hexdigest()
    return check_code + ":" + digest


def empty_summary() -> dict[str, Any]:
    return dict(zip(SUMMARY_FIELDS, (0, 0, 0, 0, 0, 0, None), strict=True))


@dataclass(frozen=True)
class Difference:
    difference_type: str
    reference_key: str
    payment_order_id: str | None
    profit_sharing_order_item_id: str | None
    expected_cents: int | None
    actual_cents: int | None
    evidence: dict[str, Any]


@dataclass
class ReconciliationResult:
    differences: list[Difference] = field(default_factory=list)
    covered_keys: set[str] = field(default_factory=set)
    outcomes: dict[str, dict[str, Any]] = field(default_factory=dict)
    summary: dict[str, Any] = field(default_factory=empty_summary)
    company_summaries: dict[str, dict[str, Any]] = field(default_factory=dict)
    fees: dict[str, int] = field(default_factory=dict)
    fee_sources: dict[str, dict[str, Any]] = field(default_factory=dict)

    def group(self, company_id: str | None) -> list[dict[str, Any]]:
        return [self.summary] + (
            [self.company_summaries.setdefault(company_id, empty_summary())] if company_id else []
        )

    def count(
        self,
        kind: str,
        *,
        company_id: str | None,
        amount: int | None = None,
        fee: int | None = None,
    ) -> None:
        for summary in self.group(company_id):
            summary[kind + "_count"] += 1
            if amount is not None and kind in {"local", "channel"}:
                summary[kind + "_amount_cents"] += amount
            if fee is not None:
                summary["channel_fee_cents"] = (summary["channel_fee_cents"] or 0) + fee

    def check(
        self,
        code: str,
        identity: tuple[str, ...],
        *,
        source: str,
        now: datetime,
        source_digest: str | None = None,
        source_request_id: str | None = None,
        local: dict[str, Any] | None = None,
        row: dict[str, Any] | None = None,
        difference: str | None = None,
        expected: int | None = None,
        actual: int | None = None,
        expected_status: str | None = None,
        actual_status: str | None = None,
    ) -> None:
        key = reference_key(code, *identity)
        self.covered_keys.add(key)
        local, row = local or {}, row or {}
        if code == "business_identity":
            row = {}
        evidence = {
            "source": source,
            "check_code": code,
            "source_digest": source_digest,
            "source_request_id": source_request_id,
            "order_no": row.get("order_no", local.get("order_no")),
            "channel_transaction_no": row.get(
                "channel_transaction_no", local.get("channel_transaction_no")
            ),
            "channel_order_no": row.get("channel_order_no", local.get("channel_order_no")),
            "channel_detail_no": row.get("channel_detail_no", local.get("channel_detail_no")),
            "statement_line_no": None,
            "expected_status": expected_status,
            "actual_status": actual_status,
            "checked_at": now.isoformat(),
        }
        self.outcomes[key] = {
            "expected_cents": expected,
            "actual_cents": actual,
            "evidence": evidence,
        }
        if difference is None:
            return
        self.differences.append(
            Difference(
                difference,
                key,
                local.get("payment_id"),
                local.get("item_id"),
                expected,
                actual,
                evidence,
            )
        )
        for summary in self.group(local.get("company_id")):
            summary["discrepancy_count"] += 1


def compare_trade(
    rows: tuple[dict[str, Any], ...],
    local: list[dict[str, Any]],
    *,
    day: date,
    provider: str,
    merchant: str,
    app_id: str,
    now: datetime,
    source_digest: str,
    source_request_id: str,
) -> ReconciliationResult:
    result = ReconciliationResult()
    by_number = {p["order_no"]: p for p in local}
    seen: set[str] = set()
    for row in rows:
        number = row["order_no"]
        if number in seen or business_date(row["paid_at"]) != day or row["channel_fee_cents"] < 0:
            raise ValueError("Invalid or duplicate trade statement business scope")
        seen.add(number)
        payment = by_number.get(number)
        # Merchant number alone does not prove local payment ownership.
        identity_ok = bool(
            payment
            and row["service_provider_merchant_no"] == provider
            and row["merchant_no"] == merchant
            and row["app_id"] == app_id
            and payment["provider"] == provider
            and payment["merchant"] == merchant
            and payment["channel_transaction_no"] in {None, row["channel_transaction_no"]}
            and row.get("currency") == "CNY"
            and (
                not row.get("payer_identity_digest")
                or row["payer_identity_digest"] == payment["payer_digest"]
            )
        )
        company = payment["company_id"] if identity_ok and payment else None
        result.count(
            "channel", company_id=company, amount=row["amount_cents"], fee=row["channel_fee_cents"]
        )
        args: dict[str, Any] = dict(
            source="channel_trade",
            now=now,
            source_digest=source_digest,
            source_request_id=source_request_id,
            row=row,
        )
        if payment is None:
            result.check(
                "payment_amount",
                (number,),
                difference="channel_only",
                actual=row["amount_cents"],
                **args,
            )
            continue
        result.check(
            "business_identity",
            (number,),
            local=payment,
            difference=None if identity_ok else "status_mismatch",
            **args,
        )
        if not identity_ok:
            continue
        before = len(result.differences)
        result.check(
            "payment_amount",
            (number,),
            local=payment,
            expected=payment["amount_cents"],
            actual=row["amount_cents"],
            difference=None
            if payment["amount_cents"] == row["amount_cents"]
            else "amount_mismatch",
            **args,
        )
        status_ok = payment["status"] == "succeeded" and row["channel_status"] == "SUCCESS"
        result.check(
            "payment_status",
            (number,),
            local=payment,
            expected_status=payment["status"],
            actual_status=row["channel_status"],
            difference=None if status_ok else "status_mismatch",
            **args,
        )
        known_fee = payment["channel_fee_cents"]
        result.check(
            "channel_fee",
            (number,),
            local=payment,
            expected=known_fee,
            actual=row["channel_fee_cents"],
            difference="amount_mismatch"
            if known_fee is not None and known_fee != row["channel_fee_cents"]
            else None,
            **args,
        )
        if payment["status"] == "succeeded" and status_ok:
            result.fees[payment["payment_id"]] = (
                known_fee if known_fee is not None else row["channel_fee_cents"]
            )
            result.fee_sources[payment["payment_id"]] = payment.get("channel_fee_source") or {
                "source_request_id": source_request_id,
                "source_digest": source_digest,
            }
        if len(result.differences) == before:
            result.count("matched", company_id=company)
    for payment in local:
        if payment["status"] != "succeeded" or business_date(payment["paid_at"]) != day:
            continue
        result.count("local", company_id=payment["company_id"], amount=payment["amount_cents"])
        if payment["order_no"] not in seen:
            result.check(
                "payment_amount",
                (payment["order_no"],),
                source="channel_trade",
                now=now,
                source_digest=source_digest,
                source_request_id=source_request_id,
                local=payment,
                expected=payment["amount_cents"],
                difference="local_only",
            )
    return result


def compare_sharing(
    rows: tuple[dict[str, Any], ...],
    local: list[dict[str, Any]],
    *,
    day: date,
    provider: str,
    merchant: str,
    now: datetime,
    source_digest: str,
    source_request_id: str,
) -> ReconciliationResult:
    result = ReconciliationResult()
    by_identity = {(item["order_no"], item["receiver_account"]): item for item in local}
    seen: set[tuple[str, str]] = set()
    for row in rows:
        identity = (
            row["order_no"],
            row.get("receiver_account") or row.get("receiver_identity_digest") or "unknown",
        )
        if identity in seen or business_date(row["finished_at"]) != day:
            raise ValueError("Invalid or duplicate sharing statement business scope")
        seen.add(identity)
        item = by_identity.get(identity)
        valid = bool(
            item
            and row["service_provider_merchant_no"] == provider
            and row["merchant_no"] == merchant
            and item["provider"] == provider
            and item["merchant"] == merchant
            and row["channel_transaction_no"] == item["channel_transaction_no"]
            and row.get("receiver_type") == "merchant"
            and item["channel_order_no"] in {None, row["channel_order_no"]}
        )
        company = item["company_id"] if valid and item else None
        result.count("channel", company_id=company, amount=row["amount_cents"])
        args: dict[str, Any] = dict(
            source="channel_profit_sharing",
            now=now,
            source_digest=source_digest,
            source_request_id=source_request_id,
            row=row,
        )
        if item is None:
            result.check(
                "profit_sharing_amount",
                identity,
                difference="channel_only",
                actual=row["amount_cents"],
                **args,
            )
            continue
        result.check(
            "business_identity",
            identity,
            local=item,
            difference=None if valid else "status_mismatch",
            **args,
        )
        if not valid:
            continue
        before = len(result.differences)
        result.check(
            "profit_sharing_amount",
            identity,
            local=item,
            expected=item["amount_cents"],
            actual=row["amount_cents"],
            difference=None if item["amount_cents"] == row["amount_cents"] else "amount_mismatch",
            **args,
        )
        expected = (
            "SUCCESS"
            if item["result"] == "success"
            else ("CLOSED" if item["result"] == "failed" else "PENDING")
        )
        result.check(
            "profit_sharing_status",
            identity,
            local=item,
            expected_status=expected,
            actual_status=row["channel_status"],
            difference=None if expected == row["channel_status"] else "status_mismatch",
            **args,
        )
        if len(result.differences) == before:
            result.count("matched", company_id=company)
    for item in local:
        if (
            item["result"] != "success"
            or not item["finished_at"]
            or business_date(item["finished_at"]) != day
        ):
            continue
        result.count("local", company_id=item["company_id"], amount=item["amount_cents"])
        identity = (item["order_no"], item["receiver_account"])
        if identity not in seen:
            result.check(
                "profit_sharing_amount",
                identity,
                source="channel_profit_sharing",
                now=now,
                source_digest=source_digest,
                source_request_id=source_request_id,
                local=item,
                expected=item["amount_cents"],
                difference="local_only",
            )
    return result


def compare_fundflow(
    rows: tuple[dict[str, Any], ...],
    local: list[dict[str, Any]],
    *,
    now: datetime,
    source_digest: str,
    source_request_id: str,
    receiver_account: str,
) -> ReconciliationResult:
    result = ReconciliationResult()
    seen: set[str] = set()
    for row in rows:
        number = row["channel_record_no"]
        if number in seen:
            raise ValueError("Duplicate platform fundflow record")
        seen.add(number)
        candidates = [
            item
            for item in local
            if item["result"] == "success"
            and item["receiver_account"] == receiver_account
            and (
                (
                    row.get("channel_detail_no")
                    and row["channel_detail_no"] == item["channel_detail_no"]
                )
                or (row["channel_order_no"] == item["channel_order_no"])
            )
        ]
        item = candidates[0] if len(candidates) == 1 else None
        supported = row.get("direction") == "收入" and "分账" in row.get(
            "channel_business_name", ""
        )
        company = item["company_id"] if item and supported else None
        result.count("channel", company_id=company, amount=row["amount_cents"])
        args: dict[str, Any] = dict(
            source="channel_fundflow",
            now=now,
            source_digest=source_digest,
            source_request_id=source_request_id,
            row=row,
        )
        if item is None or not supported:
            result.check(
                "platform_fundflow_amount",
                (number,),
                difference="unclassified",
                actual=row["amount_cents"],
                **args,
            )
            continue
        result.count("local", company_id=company, amount=item["amount_cents"])
        result.check(
            "platform_fundflow_amount",
            (number,),
            local=item,
            expected=item["amount_cents"],
            actual=row["amount_cents"],
            difference=None if item["amount_cents"] == row["amount_cents"] else "amount_mismatch",
            **args,
        )
        if item["amount_cents"] == row["amount_cents"]:
            result.count("matched", company_id=company)
    # Sharing finish time cannot establish the platform account's booking date.
    return result
