from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend_app.core.identifiers import new_id
from backend_app.domain.payments.funds import (
    FundsBlocked,
    calculate_allocations,
    remaining_allocations,
)
from backend_app.models.payments import (
    PaymentOrder,
    PaymentTask,
    PaymentUnfreezeOrder,
    ProfitSharingAllocation,
    ProfitSharingOrder,
    ProfitSharingOrderItem,
    ProfitSharingRuleVersion,
    ProfitSharingRuleVersionItem,
)
from backend_app.repositories.payments.tasks import ensure_task

INFLIGHT = {"pending", "unknown", "processing"}


class FundsRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def lock_payment(self, payment_id: str) -> PaymentOrder:
        return self.db.scalars(
            select(PaymentOrder)
            .where(PaymentOrder.id == payment_id)
            .with_for_update(of=PaymentOrder)
            .execution_options(populate_existing=True)
        ).one()

    def allocations(self, payment_id: str) -> list[ProfitSharingAllocation]:
        return list(
            self.db.scalars(
                select(ProfitSharingAllocation)
                .where(ProfitSharingAllocation.payment_order_id == payment_id)
                .order_by(ProfitSharingAllocation.id)
            )
        )

    def sharing_orders(self, payment_id: str) -> list[ProfitSharingOrder]:
        return list(
            self.db.scalars(
                select(ProfitSharingOrder)
                .where(ProfitSharingOrder.payment_order_id == payment_id)
                .order_by(ProfitSharingOrder.created_at, ProfitSharingOrder.id)
            )
        )

    def sharing_items(self, sharing_id: str) -> list[ProfitSharingOrderItem]:
        return list(
            self.db.scalars(
                select(ProfitSharingOrderItem)
                .where(ProfitSharingOrderItem.profit_sharing_order_id == sharing_id)
                .order_by(ProfitSharingOrderItem.id)
            )
        )

    def unfreeze_orders(self, payment_id: str) -> list[PaymentUnfreezeOrder]:
        return list(
            self.db.scalars(
                select(PaymentUnfreezeOrder)
                .where(PaymentUnfreezeOrder.payment_order_id == payment_id)
                .order_by(PaymentUnfreezeOrder.created_at, PaymentUnfreezeOrder.id)
            )
        )

    def rule_items(self, rule_id: str) -> list[ProfitSharingRuleVersionItem]:
        return list(
            self.db.scalars(
                select(ProfitSharingRuleVersionItem)
                .where(ProfitSharingRuleVersionItem.rule_version_id == rule_id)
                .order_by(ProfitSharingRuleVersionItem.id)
            )
        )

    def remaining(self, payment_id: str) -> dict[str, int]:
        owed = {
            allocation.id: allocation.amount_cents for allocation in self.allocations(payment_id)
        }
        successful = {
            allocation_id: int(amount)
            for allocation_id, amount in self.db.execute(
                select(
                    ProfitSharingOrderItem.allocation_id,
                    func.sum(ProfitSharingOrderItem.amount_cents),
                )
                .where(
                    ProfitSharingOrderItem.payment_order_id == payment_id,
                    ProfitSharingOrderItem.result == "success",
                )
                .group_by(ProfitSharingOrderItem.allocation_id)
            ).all()
        }
        return remaining_allocations(owed, successful)

    def create_allocations(self, payment: PaymentOrder) -> None:
        if payment.status != "succeeded":
            raise FundsBlocked("PAYMENT_NOT_POSTED")
        rule = self.db.get(ProfitSharingRuleVersion, payment.rule_version_id)
        assert rule is not None
        amounts = calculate_allocations(
            payment.amount_cents,
            {item.id: item.rate_bps for item in self.rule_items(rule.id)},
            calculation_version=rule.calculation_version,
        )
        existing = {a.rule_version_item_id: a.amount_cents for a in self.allocations(payment.id)}
        if existing:
            if existing != amounts:
                raise FundsBlocked("ALLOCATION_FACTS_CONFLICT")
            return
        self.db.add_all(
            [
                ProfitSharingAllocation(
                    payment_order_id=payment.id,
                    rule_version_item_id=item_id,
                    amount_cents=amount,
                )
                for item_id, amount in amounts.items()
            ]
        )
        self.db.flush()

    def create_sharing(
        self, payment: PaymentOrder, *, now: datetime, next_run_at: datetime | None = None
    ) -> ProfitSharingOrder | None:
        """Caller holds the payment parent; preserve every earlier execution and its results."""
        if payment.status != "succeeded":
            raise FundsBlocked("PAYMENT_NOT_POSTED")
        if self.unfreeze_orders(payment.id):
            raise FundsBlocked("UNFREEZE_BARRIER")
        orders = self.sharing_orders(payment.id)
        for order in orders:
            if order.status in INFLIGHT:
                return order
        remaining = self.remaining(payment.id)
        if not remaining:
            return None
        accepted = sum(
            order.channel_order_no is not None or order.status == "finished" for order in orders
        )
        if accepted >= 50:
            raise FundsBlocked("SHARING_ACCEPTANCE_LIMIT")
        order = ProfitSharingOrder(
            payment_order_id=payment.id,
            order_no="ps_" + new_id().replace("-", ""),
            created_at=now,
            updated_at=now,
        )
        self.db.add(order)
        self.db.flush()
        self.db.add_all(
            [
                ProfitSharingOrderItem(
                    payment_order_id=payment.id,
                    profit_sharing_order_id=order.id,
                    allocation_id=allocation_id,
                    amount_cents=amount,
                    created_at=now,
                    updated_at=now,
                )
                for allocation_id, amount in remaining.items()
            ]
        )
        self.db.flush()
        assert payment.paid_at is not None
        due = max(next_run_at or now, payment.paid_at + timedelta(minutes=1))
        ensure_task(self.db, "profit_sharing_submit", order.id, now=now, next_run_at=due)
        return order

    def create_unfreeze(self, payment: PaymentOrder, *, now: datetime) -> PaymentUnfreezeOrder:
        if payment.status != "succeeded" or self.remaining(payment.id):
            raise FundsBlocked("SHARING_NOT_FULFILLED")
        if any(order.status in INFLIGHT for order in self.sharing_orders(payment.id)):
            raise FundsBlocked("SHARING_INFLIGHT")
        orders = self.unfreeze_orders(payment.id)
        if orders and orders[-1].status != "failed":
            return orders[-1]
        order = PaymentUnfreezeOrder(
            payment_order_id=payment.id,
            order_no="uf_" + new_id().replace("-", ""),
            created_at=now,
            updated_at=now,
        )
        self.db.add(order)
        self.db.flush()
        ensure_task(self.db, "unfreeze_submit", order.id, now=now)
        return order

    def initialize_funds(self, payment: PaymentOrder, *, now: datetime) -> None:
        self.create_allocations(payment)
        if self.allocations(payment.id):
            self.create_sharing(payment, now=now)
        else:
            self.create_unfreeze(payment, now=now)

    def recover(self, payment: PaymentOrder, *, now: datetime) -> PaymentTask | None:
        """Schedule the original inflight operation, or safely create only unfulfilled work."""
        unfreezes = self.unfreeze_orders(payment.id)
        if not unfreezes and not self.allocations(payment.id):
            # Legal zero-obligation confirmation already creates its unfreeze atomically.
            raise FundsBlocked("INITIAL_FUNDS_FACTS_MISSING")
        if unfreezes:
            order = unfreezes[-1]
            if order.status in {"succeeded", "no_remaining"}:
                return None
            if order.status == "failed":
                order = self.create_unfreeze(payment, now=now)
                task_type = "unfreeze_submit"
            else:
                task_type = "unfreeze_submit" if order.status == "pending" else "unfreeze_query"
            return ensure_task(self.db, task_type, order.id, now=now, reactivate=True)
        for sharing in self.sharing_orders(payment.id):
            if sharing.status in INFLIGHT:
                task_type = (
                    "profit_sharing_submit"
                    if sharing.status == "pending"
                    else "profit_sharing_query"
                )
                return ensure_task(self.db, task_type, sharing.id, now=now, reactivate=True)
        if self.remaining(payment.id):
            new_sharing = self.create_sharing(payment, now=now)
            assert new_sharing is not None
            return ensure_task(
                self.db, "profit_sharing_submit", new_sharing.id, now=now, reactivate=True
            )
        unfreeze = self.create_unfreeze(payment, now=now)
        return ensure_task(self.db, "unfreeze_submit", unfreeze.id, now=now, reactivate=True)
