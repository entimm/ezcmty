from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from backend_app.core.identifiers import new_id
from backend_app.domain.payments.reconciliation import (
    BUSINESS_ZONE,
    ReconciliationResult,
    reference_key,
)
from backend_app.integrations.wechatpay.client import identity_digest
from backend_app.models.billing import BillSettlementEntry
from backend_app.models.miniapp import MiniappUser
from backend_app.models.payments import (
    PaymentChannelRequest,
    PaymentOrder,
    PaymentOrderItem,
    PaymentReconciliationDiscrepancy,
    PaymentReconciliationRun,
    PaymentTask,
    PaymentUnfreezeOrder,
    ProfitSharingAllocation,
    ProfitSharingOrder,
    ProfitSharingOrderItem,
    ProfitSharingRuleVersionItem,
    PropertyMerchantBinding,
)
from backend_app.repositories.payments.tasks import ensure_task


def lock_run(db: Session, run_id: str) -> PaymentReconciliationRun:
    return db.scalars(
        select(PaymentReconciliationRun)
        .where(PaymentReconciliationRun.id == run_id)
        .with_for_update(of=PaymentReconciliationRun)
        .execution_options(populate_existing=True)
    ).one()


def schedule_reconciliation(
    db: Session, run: PaymentReconciliationRun, *, now: datetime
) -> PaymentTask:
    task = ensure_task(db, "reconciliation", run.id, now=now, reactivate=True)
    if task.status != "running":
        run.status = "ready"
        run.finished_at = None
        run.updated_at = now
    db.flush()
    return task


def ensure_run(
    db: Session,
    *,
    day: date,
    statement_type: str,
    provider: str,
    merchant: str | None,
    now: datetime,
) -> tuple[PaymentReconciliationRun, bool]:
    inserted = db.scalar(
        insert(PaymentReconciliationRun)
        .values(
            id=new_id(),
            business_date=day,
            statement_type=statement_type,
            service_provider_merchant_no=provider,
            merchant_no=merchant,
            status="ready",
            summary={},
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_nothing(constraint="uq_payment_reconciliation_scope")
        .returning(PaymentReconciliationRun.id)
    )
    run = db.scalars(
        select(PaymentReconciliationRun).where(
            PaymentReconciliationRun.business_date == day,
            PaymentReconciliationRun.statement_type == statement_type,
            PaymentReconciliationRun.service_provider_merchant_no == provider,
            PaymentReconciliationRun.merchant_no == merchant,
        )
    ).one()
    if inserted is not None:
        ensure_task(db, "reconciliation", run.id, now=now)
    elif run.status in {"ready", "failed"}:
        # Existing paused failures retain their diagnostic and explicit recovery boundary.
        ensure_task(db, "reconciliation", run.id, now=now)
    return run, inserted is not None


def day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, BUSINESS_ZONE)
    return start, start + timedelta(days=1)


class ReconciliationRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def unfreeze_facts(self, run: PaymentReconciliationRun) -> list[dict[str, Any]]:
        start, end = day_bounds(run.business_date)
        rows = self.db.execute(
            select(PaymentUnfreezeOrder, PaymentOrder, PropertyMerchantBinding)
            .join(PaymentOrder, PaymentUnfreezeOrder.payment_order_id == PaymentOrder.id)
            .join(
                PropertyMerchantBinding,
                PaymentOrder.merchant_binding_id == PropertyMerchantBinding.id,
            )
            .where(
                PropertyMerchantBinding.service_provider_merchant_no
                == run.service_provider_merchant_no,
                PropertyMerchantBinding.merchant_no == run.merchant_no,
                or_(
                    and_(PaymentOrder.paid_at >= start, PaymentOrder.paid_at < end),
                    and_(
                        PaymentUnfreezeOrder.finished_at >= start,
                        PaymentUnfreezeOrder.finished_at < end,
                    ),
                ),
            )
        )
        return [
            {
                "payment_id": payment.id,
                "company_id": payment.property_company_id,
                "execution_id": order.id,
                "order_no": order.order_no,
                "channel_transaction_no": payment.channel_transaction_no,
                "channel_order_no": order.channel_order_no,
                "merchant": binding.merchant_no,
                "status": order.status,
                "amount_cents": order.unfrozen_cents,
            }
            for order, payment, binding in rows
        ]

    def payment_facts(
        self, run: PaymentReconciliationRun, rows: tuple[dict[str, Any], ...]
    ) -> list[dict[str, Any]]:
        start, end = day_bounds(run.business_date)
        numbers = {row["order_no"] for row in rows if row.get("order_no")}
        previous = self.db.scalar(
            select(PaymentChannelRequest)
            .where(
                PaymentChannelRequest.reconciliation_run_id == run.id,
                PaymentChannelRequest.operation == "statement_download",
                PaymentChannelRequest.finished_at.is_not(None),
                PaymentChannelRequest.outcome == "verified_response",
            )
            .order_by(PaymentChannelRequest.created_at.desc(), PaymentChannelRequest.id.desc())
            .limit(1)
        )
        known_fees = (
            {
                decision["reference_key"]: decision
                for decision in (previous.response_snapshot or {}).get("decisions", [])
                if decision.get("check_code") == "channel_fee"
                and decision.get("actual_cents") is not None
                and decision.get("status") == "observed"
            }
            if previous is not None
            else {}
        )
        values = self.db.execute(
            select(PaymentOrder, PropertyMerchantBinding, MiniappUser)
            .join(
                PropertyMerchantBinding,
                PaymentOrder.merchant_binding_id == PropertyMerchantBinding.id,
            )
            .join(MiniappUser, PaymentOrder.payer_user_id == MiniappUser.id)
            .where(
                PropertyMerchantBinding.service_provider_merchant_no
                == run.service_provider_merchant_no,
                PropertyMerchantBinding.merchant_no == run.merchant_no,
                or_(
                    and_(PaymentOrder.paid_at >= start, PaymentOrder.paid_at < end),
                    PaymentOrder.order_no.in_(numbers),
                ),
            )
        ).all()
        return [
            {
                "payment_id": p.id,
                "company_id": p.property_company_id,
                "order_no": p.order_no,
                "channel_transaction_no": p.channel_transaction_no,
                "provider": b.service_provider_merchant_no,
                "merchant": b.merchant_no,
                "payer_digest": identity_digest(u.wechat_openid),
                "amount_cents": p.amount_cents,
                "channel_fee_cents": known_fees.get(
                    reference_key("channel_fee", p.order_no), {}
                ).get("actual_cents"),
                "channel_fee_source": known_fees.get(reference_key("channel_fee", p.order_no)),
                "status": p.status,
                "paid_at": p.paid_at,
            }
            for p, b, u in values
        ]

    def sharing_facts(
        self, run: PaymentReconciliationRun, rows: tuple[dict[str, Any], ...]
    ) -> list[dict[str, Any]]:
        start, end = day_bounds(run.business_date)
        numbers = {row["order_no"] for row in rows if row.get("order_no")}
        channel_numbers = {row["channel_order_no"] for row in rows if row.get("channel_order_no")}
        details = {row["channel_detail_no"] for row in rows if row.get("channel_detail_no")}
        scope = [
            PropertyMerchantBinding.service_provider_merchant_no == run.service_provider_merchant_no
        ]
        if run.merchant_no is not None:
            scope.append(PropertyMerchantBinding.merchant_no == run.merchant_no)
            scope.append(
                or_(
                    ProfitSharingOrder.order_no.in_(numbers),
                    and_(
                        ProfitSharingOrderItem.finished_at >= start,
                        ProfitSharingOrderItem.finished_at < end,
                    ),
                )
            )
        else:
            scope.append(
                or_(
                    ProfitSharingOrder.channel_order_no.in_(channel_numbers),
                    ProfitSharingOrderItem.channel_detail_no.in_(details),
                )
            )
        values = self.db.execute(
            select(
                ProfitSharingOrderItem,
                ProfitSharingOrder,
                ProfitSharingRuleVersionItem,
                PaymentOrder,
                PropertyMerchantBinding,
            )
            .join(
                ProfitSharingOrder,
                ProfitSharingOrderItem.profit_sharing_order_id == ProfitSharingOrder.id,
            )
            .join(
                ProfitSharingAllocation,
                ProfitSharingOrderItem.allocation_id == ProfitSharingAllocation.id,
            )
            .join(
                ProfitSharingRuleVersionItem,
                ProfitSharingAllocation.rule_version_item_id == ProfitSharingRuleVersionItem.id,
            )
            .join(PaymentOrder, ProfitSharingOrder.payment_order_id == PaymentOrder.id)
            .join(
                PropertyMerchantBinding,
                PaymentOrder.merchant_binding_id == PropertyMerchantBinding.id,
            )
            .where(*scope)
        ).all()
        return [
            {
                "payment_id": p.id,
                "company_id": p.property_company_id,
                "item_id": i.id,
                "order_no": o.order_no,
                "channel_transaction_no": p.channel_transaction_no,
                "channel_order_no": o.channel_order_no,
                "channel_detail_no": i.channel_detail_no,
                "provider": b.service_provider_merchant_no,
                "merchant": b.merchant_no,
                "receiver_account": r.receiver_account,
                "amount_cents": i.amount_cents,
                "result": i.result,
                "finished_at": i.finished_at,
            }
            for i, o, r, p, b in values
        ]

    def internal_checks(
        self,
        run: PaymentReconciliationRun,
        result: ReconciliationResult,
        payments: list[dict[str, Any]],
        *,
        now: datetime,
    ) -> None:
        for payment in payments:
            if payment["status"] != "succeeded":
                continue
            for item in self.db.scalars(
                select(PaymentOrderItem).where(
                    PaymentOrderItem.payment_order_id == payment["payment_id"]
                )
            ):
                entries = list(
                    self.db.scalars(
                        select(BillSettlementEntry).where(
                            BillSettlementEntry.payment_order_item_id == item.id
                        )
                    )
                )
                actual = sum(entry.amount_cents for entry in entries) if entries else None
                result.check(
                    "bill_posting",
                    (item.id,),
                    source="internal",
                    now=now,
                    local=payment,
                    expected=item.amount_cents,
                    actual=actual,
                    difference="status_mismatch"
                    if not entries
                    else ("amount_mismatch" if actual != item.amount_cents else None),
                )
            allocations = list(
                self.db.scalars(
                    select(ProfitSharingAllocation).where(
                        ProfitSharingAllocation.payment_order_id == payment["payment_id"]
                    )
                )
            )
            for allocation in allocations:
                actual = sum(
                    self.db.scalars(
                        select(ProfitSharingOrderItem.amount_cents).where(
                            ProfitSharingOrderItem.allocation_id == allocation.id,
                            ProfitSharingOrderItem.result == "success",
                        )
                    )
                )
                result.check(
                    "profit_sharing_amount",
                    ("allocation", allocation.id),
                    source="internal",
                    now=now,
                    local=payment,
                    expected=allocation.amount_cents,
                    actual=actual,
                    difference="amount_mismatch" if actual != allocation.amount_cents else None,
                )

    def apply_result(
        self, run: PaymentReconciliationRun, result: ReconciliationResult, *, now: datetime
    ) -> list[dict[str, Any]]:
        existing = list(
            self.db.scalars(
                select(PaymentReconciliationDiscrepancy)
                .where(PaymentReconciliationDiscrepancy.reconciliation_run_id == run.id)
                .order_by(PaymentReconciliationDiscrepancy.id)
                .with_for_update(of=PaymentReconciliationDiscrepancy)
            )
        )
        by_key = {(d.difference_type, d.reference_key): d for d in existing}
        present: set[tuple[str, str]] = set()
        decisions: list[dict[str, Any]] = []
        for difference in result.differences:
            key = difference.difference_type, difference.reference_key
            if key in present:
                raise ValueError("Duplicate reconciliation decision")
            present.add(key)
            row = by_key.get(key)
            if row is None:
                row = PaymentReconciliationDiscrepancy(
                    reconciliation_run_id=run.id,
                    difference_type=difference.difference_type,
                    reference_key=difference.reference_key,
                    evidence=difference.evidence,
                    created_at=now,
                    updated_at=now,
                )
                self.db.add(row)
            row.payment_order_id = difference.payment_order_id
            row.profit_sharing_order_item_id = difference.profit_sharing_order_item_id
            row.expected_cents, row.actual_cents = (
                difference.expected_cents,
                difference.actual_cents,
            )
            row.evidence = difference.evidence
            row.status = "open"
            row.updated_at = now
            decisions.append(
                {
                    "reference_key": row.reference_key,
                    "difference_type": row.difference_type,
                    "check_code": difference.evidence["check_code"],
                    "expected_cents": row.expected_cents,
                    "actual_cents": row.actual_cents,
                    "status": "open",
                    "evidence": row.evidence,
                }
            )
        for row in existing:
            if (
                row.difference_type,
                row.reference_key,
            ) not in present and row.reference_key in result.covered_keys:
                outcome = result.outcomes[row.reference_key]
                row.expected_cents, row.actual_cents = (
                    outcome["expected_cents"],
                    outcome["actual_cents"],
                )
                row.evidence = outcome["evidence"]
                row.status = "resolved"
                row.resolved_at = now
                row.resolved_by = None
                row.updated_at = now
                # Keep administrator attribution; immutable snapshots explain automation.
                decisions.append(
                    {
                        "reference_key": row.reference_key,
                        "difference_type": row.difference_type,
                        "check_code": row.evidence["check_code"],
                        "expected_cents": row.expected_cents,
                        "actual_cents": row.actual_cents,
                        "status": "resolved",
                        "evidence": row.evidence,
                    }
                )
        for payment_id, fee in result.fees.items():
            payment = self.db.get(PaymentOrder, payment_id)
            assert payment is not None
            decisions.append(
                {
                    "reference_key": reference_key("channel_fee", payment.order_no),
                    "check_code": "channel_fee",
                    "expected_cents": None,
                    "actual_cents": fee,
                    "status": "observed",
                    "source_request_id": result.fee_sources[payment_id]["source_request_id"],
                    "source_digest": result.fee_sources[payment_id]["source_digest"],
                }
            )
        run.summary = result.summary | {"company_summaries": result.company_summaries}
        self.db.flush()
        return decisions
