from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from backend_app.models.admin import utc_now
from backend_app.models.payments import (
    PaymentReconciliationDiscrepancy,
    PaymentReconciliationRun,
)
from tests.support.payment_api import PaymentHouse, billing_setup_for_house
from tests.support.payments import PaymentSetup, complete_payment, provision_payment


@dataclass(frozen=True)
class ManagedScenario:
    payment: PaymentSetup
    run_id: str
    linked_difference_id: str
    unlinked_difference_id: str
    platform_run_id: str


def reconciliation_evidence(*, check_code: str = "payment_amount") -> dict[str, Any]:
    return {
        "source": "internal",
        "check_code": check_code,
        "source_digest": "SHA256:isolated_digest",
        "source_request_id": None,
        "order_no": "isolated_order",
        "channel_transaction_no": None,
        "channel_order_no": None,
        "channel_detail_no": None,
        "statement_line_no": None,
        "expected_status": "succeeded",
        "actual_status": "unknown",
        "checked_at": utc_now().isoformat(),
        "private_raw_statement": "敏感全量账单不可展示",
        "payer_openid": "sensitive-openid",
        "phone": "13800138000",
    }


def add_discrepancy(
    db: Session,
    run: PaymentReconciliationRun,
    *,
    payment_id: str | None,
    reference: str,
    check_code: str = "payment_amount",
) -> PaymentReconciliationDiscrepancy:
    item = PaymentReconciliationDiscrepancy(
        reconciliation_run_id=run.id,
        difference_type="amount_mismatch" if payment_id else "channel_only",
        reference_key=reference,
        payment_order_id=payment_id,
        expected_cents=7000 if payment_id else None,
        actual_cents=7100,
        evidence=reconciliation_evidence(check_code=check_code),
    )
    db.add(item)
    db.flush()
    return item


def managed_scenario(
    house: PaymentHouse, *, complete: bool = True, rate_bps: int = 300
) -> ManagedScenario:
    setup = billing_setup_for_house(house)
    with setup.factory() as db:
        payment = provision_payment(
            db,
            setup,
            bill_id=house.bill_id,
            payer_user_id=house.resident.user_id,
            rate_bps=rate_bps,
        )
        if complete:
            complete_payment(db, payment)
        summary = {
            "local_count": 99,
            "channel_count": 100,
            "matched_count": 98,
            "discrepancy_count": 2,
            "local_amount_cents": 990000,
            "channel_amount_cents": 990100,
            "channel_fee_cents": 200,
            "private_summary": "禁止向物业返回",
            "company_summaries": {
                house.workspace.company_id: {
                    "local_count": 1,
                    "channel_count": 1,
                    "matched_count": 0,
                    "discrepancy_count": 1,
                    "local_amount_cents": 7000,
                    "channel_amount_cents": 7100,
                    "channel_fee_cents": None,
                }
            },
        }
        run = PaymentReconciliationRun(
            business_date=date(2026, 10, 18),
            statement_type="trade",
            service_provider_merchant_no="1900000001",
            merchant_no="1900000002",
            status="completed",
            statement_hash_type="SHA256",
            statement_hash="isolated_hash",
            summary=summary,
            finished_at=utc_now(),
        )
        platform_run = PaymentReconciliationRun(
            business_date=date(2026, 10, 18),
            statement_type="platform_fundflow",
            service_provider_merchant_no="1900000001",
            merchant_no=None,
        )
        db.add_all([run, platform_run])
        db.flush()
        linked = add_discrepancy(db, run, payment_id=payment.order_id, reference="linked")
        unlinked = add_discrepancy(db, run, payment_id=None, reference="unlinked")
        result = ManagedScenario(payment, run.id, linked.id, unlinked.id, platform_run.id)
        db.commit()
    return result
