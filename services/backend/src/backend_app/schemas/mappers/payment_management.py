from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend_app.domain.payments.configuration import fingerprint
from backend_app.models.payments import (
    PaymentChannelNotification,
    PaymentChannelRequest,
    PaymentOrder,
    PaymentReconciliationDiscrepancy,
    PaymentReconciliationRun,
    PaymentUnfreezeOrder,
    ProfitSharingAllocation,
    ProfitSharingOrder,
    ProfitSharingRuleVersionItem,
)
from backend_app.repositories.payments.funds import FundsRepository
from backend_app.repositories.payments.orders import OrdersRepository
from backend_app.schemas.payments import management as schema


def canonical(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: canonical(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [canonical(v) for v in value]
    return value


def payment_token(db: Session, payment: PaymentOrder) -> str:
    funds = FundsRepository(db)
    sharings = funds.sharing_orders(payment.id)
    unfreezes = funds.unfreeze_orders(payment.id)
    requests = list(
        db.execute(
            select(
                PaymentChannelRequest.id,
                PaymentChannelRequest.outcome,
                PaymentChannelRequest.finished_at,
            )
            .where(
                (PaymentChannelRequest.payment_order_id == payment.id)
                | PaymentChannelRequest.profit_sharing_order_id.in_([s.id for s in sharings])
                | PaymentChannelRequest.unfreeze_order_id.in_([u.id for u in unfreezes])
            )
            .order_by(PaymentChannelRequest.id)
        ).tuples()
    )
    notifications = list(
        db.execute(
            select(
                PaymentChannelNotification.id,
                PaymentChannelNotification.status,
                PaymentChannelNotification.payload,
            )
            .where(PaymentChannelNotification.payload["order_no"].as_string() == payment.order_no)
            .order_by(PaymentChannelNotification.id)
        ).tuples()
    )
    return fingerprint(
        canonical(
            {
                "payment": [
                    payment.id,
                    payment.status,
                    payment.channel_transaction_no,
                    payment.updated_at,
                ],
                "sharing": [
                    [
                        s.id,
                        s.status,
                        s.updated_at,
                        [
                            [i.id, i.result, i.amount_cents, i.finished_at]
                            for i in funds.sharing_items(s.id)
                        ],
                    ]
                    for s in sharings
                ],
                "unfreezes": [
                    [u.id, u.status, u.unfrozen_cents, u.finished_at, u.updated_at]
                    for u in unfreezes
                ],
                "requests": [list(r) for r in requests],
                "notifications": [list(n) for n in notifications],
            }
        )
    )


def payment_view(db: Session, payment: PaymentOrder, *, app_id: str) -> schema.ManagedPaymentOrder:
    repo = OrdersRepository(db)
    binding = repo.binding(payment)
    confirmation = (
        "posted"
        if payment.status == "succeeded"
        else "awaiting_posting"
        if repo.awaiting_posting(payment, app_id=app_id)
        else "unconfirmed"
    )
    return schema.ManagedPaymentOrder.model_validate(
        {
            "id": payment.id,
            "property_company_id": payment.property_company_id,
            "order_no": payment.order_no,
            "channel_transaction_no": payment.channel_transaction_no,
            "merchant_binding_id": binding.id,
            "rule_version_id": payment.rule_version_id,
            "merchant_name": binding.merchant_name,
            "merchant_no": binding.merchant_no,
            "amount_cents": payment.amount_cents,
            "payer_total_cents": payment.payer_total_cents,
            "status": payment.status,
            "confirmation_status": confirmation,
            "items": [
                {
                    "id": i.id,
                    "bill_id": bill.id,
                    "community_id": bill.community_id,
                    "house_id": bill.house_id,
                    "house_label": bill.house_label_snapshot,
                    "billing_month": bill.period_start.strftime("%Y-%m"),
                    "amount_cents": i.amount_cents,
                }
                for i, bill in repo.items(payment.id)
            ],
            "expires_at": payment.expires_at,
            "paid_at": payment.paid_at,
            "closed_at": payment.closed_at,
            "created_at": payment.created_at,
            "updated_at": payment.updated_at,
            "state_token": payment_token(db, payment),
        }
    )


def sharing_view(db: Session, order: ProfitSharingOrder) -> schema.ManagedProfitSharingOrder:
    payment = db.get(PaymentOrder, order.payment_order_id)
    assert payment is not None
    items = []
    for item in FundsRepository(db).sharing_items(order.id):
        allocation = db.get(ProfitSharingAllocation, item.allocation_id)
        assert allocation is not None
        receiver = db.get(ProfitSharingRuleVersionItem, allocation.rule_version_item_id)
        assert receiver is not None
        items.append(
            {
                "id": item.id,
                "allocation_id": allocation.id,
                "receiver_type": receiver.receiver_type,
                "receiver_account": receiver.receiver_account,
                "receiver_name": receiver.receiver_name,
                "allocation_cents": allocation.amount_cents,
                "amount_cents": item.amount_cents,
                "result": item.result,
                "channel_detail_no": item.channel_detail_no,
                "failure_summary": item.fail_reason,
                "finished_at": item.finished_at,
            }
        )
    return schema.ManagedProfitSharingOrder.model_validate(
        {
            "id": order.id,
            "property_company_id": payment.property_company_id,
            "payment_order_id": payment.id,
            "order_no": order.order_no,
            "channel_order_no": order.channel_order_no,
            "status": order.status,
            "items": items,
            "created_at": order.created_at,
            "updated_at": order.updated_at,
        }
    )


def unfreeze_view(db: Session, order: PaymentUnfreezeOrder) -> schema.ManagedUnfreezeOrder:
    payment = db.get(PaymentOrder, order.payment_order_id)
    assert payment is not None
    return schema.ManagedUnfreezeOrder.model_validate(
        {
            "id": order.id,
            "property_company_id": payment.property_company_id,
            "payment_order_id": payment.id,
            "order_no": order.order_no,
            "channel_order_no": order.channel_order_no,
            "status": order.status,
            "unfrozen_cents": order.unfrozen_cents,
            "channel_detail_no": order.channel_detail_no,
            "failure_summary": order.fail_reason,
            "finished_at": order.finished_at,
            "created_at": order.created_at,
            "updated_at": order.updated_at,
        }
    )


def run_token(run: PaymentReconciliationRun) -> str:
    return fingerprint(
        canonical(
            {
                "id": run.id,
                "status": run.status,
                "summary": run.summary,
                "source": [run.statement_hash_type, run.statement_hash],
                "finished_at": run.finished_at,
                "updated_at": run.updated_at,
            }
        )
    )


def discrepancy_token(run: PaymentReconciliationRun, item: PaymentReconciliationDiscrepancy) -> str:
    return fingerprint(
        canonical(
            {
                "run": run_token(run),
                "id": item.id,
                "status": item.status,
                "evidence": item.evidence,
                "expected_cents": item.expected_cents,
                "actual_cents": item.actual_cents,
                "payment_order_id": item.payment_order_id,
                "profit_sharing_order_item_id": item.profit_sharing_order_item_id,
                "updated_at": item.updated_at,
                "resolved_at": item.resolved_at,
                "resolved_by": item.resolved_by,
                "resolution_note": item.resolution_note,
            }
        )
    )


def run_view(
    run: PaymentReconciliationRun, *, company_id: str | None = None
) -> schema.ManagedReconciliationRun:
    summary = (
        run.summary
        if company_id is None
        else run.summary.get("company_summaries", {}).get(company_id, {})
    )
    fields = {
        "local_count": 0,
        "channel_count": 0,
        "matched_count": 0,
        "discrepancy_count": 0,
        "local_amount_cents": None,
        "channel_amount_cents": None,
        "channel_fee_cents": None,
    }
    fields.update({k: v for k, v in summary.items() if k in fields})
    digest = f"{run.statement_hash_type}:{run.statement_hash}" if run.statement_hash else None
    return schema.ManagedReconciliationRun.model_validate(
        {
            "id": run.id,
            "business_date": run.business_date,
            "statement_type": run.statement_type,
            "service_provider_merchant_no": run.service_provider_merchant_no,
            "merchant_no": run.merchant_no,
            "status": run.status,
            "projection": "company" if company_id else "batch",
            "property_company_id": company_id,
            "source_digest": None if company_id else digest,
            "summary": fields,
            "created_at": run.created_at,
            "updated_at": run.updated_at,
            "finished_at": run.finished_at,
            "state_token": run_token(run)
            if company_id is None
            else fingerprint(
                canonical(
                    {
                        "id": run.id,
                        "summary": fields,
                        "status": run.status,
                        "updated_at": run.updated_at,
                    }
                )
            ),
        }
    )


def discrepancy_view(
    db: Session, item: PaymentReconciliationDiscrepancy
) -> schema.ManagedReconciliationDiscrepancy:
    run = db.get(PaymentReconciliationRun, item.reconciliation_run_id)
    assert run is not None
    payment = db.get(PaymentOrder, item.payment_order_id) if item.payment_order_id else None
    evidence = {k: item.evidence.get(k) for k in schema.ReconciliationEvidence.model_fields}
    return schema.ManagedReconciliationDiscrepancy.model_validate(
        {
            "id": item.id,
            "reconciliation_run_id": run.id,
            "property_company_id": payment.property_company_id if payment else None,
            "difference_type": item.difference_type,
            "reference_key": item.reference_key,
            "payment_order_id": item.payment_order_id,
            "profit_sharing_order_item_id": item.profit_sharing_order_item_id,
            "expected_cents": item.expected_cents,
            "actual_cents": item.actual_cents,
            "evidence": evidence,
            "status": item.status,
            "created_at": item.created_at,
            "updated_at": item.updated_at,
            "resolved_at": item.resolved_at,
            "resolved_by": item.resolved_by,
            "resolution_note": item.resolution_note,
            "state_token": discrepancy_token(run, item),
        }
    )
