"""Complete isolated payment aggregates for database and shared-accounting tests."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from backend_app.core.identifiers import new_id
from backend_app.domain.billing.posting import post_online_receipt
from backend_app.models.admin import utc_now
from backend_app.models.billing import Bill
from backend_app.models.miniapp import MiniappUser
from backend_app.models.payments import (
    BillPaymentReservation,
    PaymentOrder,
    PaymentOrderItem,
    PaymentTask,
    PaymentUnfreezeOrder,
    ProfitSharingAllocation,
    ProfitSharingOrder,
    ProfitSharingOrderItem,
    ProfitSharingRuleVersion,
    ProfitSharingRuleVersionItem,
    PropertyMerchantBinding,
)
from backend_app.repositories.billing import BillingRepository
from tests.support.billing_services import BillingSetup


@dataclass(frozen=True)
class PaymentSetup:
    order_id: str
    item_id: str
    binding_id: str
    rule_id: str
    rule_item_ids: tuple[str, ...]
    payer_user_id: str


def provision_payment(
    db: Session,
    setup: BillingSetup,
    *,
    bill_id: str,
    rate_bps: int = 300,
    rates: tuple[int, ...] | None = None,
    key: str = "payment",
    reserve: bool = True,
    schedule: bool = True,
    order_amount_cents: int | None = None,
    payer_user_id: str | None = None,
) -> PaymentSetup:
    """Create a whole pending aggregate, leaving commit and rollback to the test."""
    bill = db.get(Bill, bill_id)
    assert bill is not None
    if payer_user_id is None:
        payer = MiniappUser(wechat_openid=f"isolated_{new_id()}")
        db.add(payer)
    else:
        existing_payer = db.get(MiniappUser, payer_user_id)
        assert existing_payer is not None
        payer = existing_payer
    binding = PropertyMerchantBinding(
        property_company_id=setup.housing.company_id,
        service_provider_merchant_no="1900000001",
        merchant_no="1900000002",
        merchant_name="隔离物业商户",
        created_by=setup.housing.context.account_id,
        idempotency_key=f"binding_{key}",
        request_fingerprint="1" * 64,
    )
    version = ProfitSharingRuleVersion(
        property_company_id=setup.housing.company_id,
        version_no=(
            db.scalar(
                select(func.max(ProfitSharingRuleVersion.version_no)).where(
                    ProfitSharingRuleVersion.property_company_id == setup.housing.company_id
                )
            )
            or 0
        )
        + 1,
        created_by=setup.housing.context.account_id,
        idempotency_key=f"rule_{key}",
        request_fingerprint="2" * 64,
    )
    db.add_all([binding, version])
    db.flush()
    rule_items = [
        ProfitSharingRuleVersionItem(
            rule_version_id=version.id,
            receiver_account=f"1900001{index:03d}",
            receiver_name=f"隔离接收方{index}",
            rate_bps=rate,
        )
        for index, rate in enumerate(rates if rates is not None else (rate_bps,))
    ]
    db.add_all(rule_items)
    db.flush()
    order = PaymentOrder(
        property_company_id=setup.housing.company_id,
        payer_user_id=payer.id,
        merchant_binding_id=binding.id,
        rule_version_id=version.id,
        order_no="p_" + new_id().replace("-", "")[-30:],
        amount_cents=(bill.outstanding_cents if order_amount_cents is None else order_amount_cents),
        expires_at=utc_now() + timedelta(minutes=15),
        idempotency_key=key,
        request_fingerprint="3" * 64,
    )
    db.add(order)
    db.flush()
    item = PaymentOrderItem(
        property_company_id=setup.housing.company_id,
        payment_order_id=order.id,
        bill_id=bill.id,
        amount_cents=bill.outstanding_cents,
    )
    db.add(item)
    db.flush()
    if reserve:
        db.add(BillPaymentReservation(bill_id=bill.id, payment_order_id=order.id))
    if schedule:
        db.add(PaymentTask(task_type="payment_submit", payment_order_id=order.id))
    db.flush()
    return PaymentSetup(
        order.id, item.id, binding.id, version.id, tuple(i.id for i in rule_items), payer.id
    )


def complete_payment(
    db: Session,
    setup: PaymentSetup,
    *,
    paid_at: datetime | None = None,
    request_id: str = "confirmation",
) -> None:
    """Build final facts for database tests; no channel or application success path."""
    item = db.get(PaymentOrderItem, setup.item_id)
    order = db.get(PaymentOrder, setup.order_id)
    assert item is not None and order is not None
    repo = BillingRepository(db, order.property_company_id)
    bill = db.get(Bill, item.bill_id)
    assert bill is not None
    order.status = "succeeded"
    order.channel_transaction_no = "channel_" + order.id
    order.paid_at = paid_at or utc_now()
    db.flush()
    post_online_receipt(repo, bill, item, order.paid_at, request_id)
    allocations = []
    for rule_item_id in setup.rule_item_ids:
        rule_item = db.get(ProfitSharingRuleVersionItem, rule_item_id)
        assert rule_item is not None
        amount = (order.amount_cents * rule_item.rate_bps + 5000) // 10000
        if amount:
            allocations.append(
                ProfitSharingAllocation(
                    payment_order_id=order.id,
                    rule_version_item_id=rule_item.id,
                    amount_cents=amount,
                )
            )
    db.add_all(allocations)
    db.flush()
    if allocations:
        sharing = ProfitSharingOrder(
            payment_order_id=order.id, order_no="ps_" + new_id().replace("-", "")
        )
        db.add(sharing)
        db.flush()
        db.add_all(
            [
                ProfitSharingOrderItem(
                    payment_order_id=order.id,
                    profit_sharing_order_id=sharing.id,
                    allocation_id=allocation.id,
                    amount_cents=allocation.amount_cents,
                )
                for allocation in allocations
            ]
        )
        db.add(
            PaymentTask(
                task_type="profit_sharing_submit",
                profit_sharing_order_id=sharing.id,
                next_run_at=order.paid_at + timedelta(minutes=1),
            )
        )
    else:
        unfreeze = PaymentUnfreezeOrder(
            payment_order_id=order.id, order_no="uf_" + new_id().replace("-", "")
        )
        db.add(unfreeze)
        db.flush()
        db.add(PaymentTask(task_type="unfreeze_submit", unfreeze_order_id=unfreeze.id))
    db.flush()
    db.execute(
        delete(BillPaymentReservation).where(
            BillPaymentReservation.bill_id == item.bill_id,
            BillPaymentReservation.payment_order_id == order.id,
        )
    )
