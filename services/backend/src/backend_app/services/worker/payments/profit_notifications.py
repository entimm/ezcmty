from collections.abc import Callable
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from backend_app.models.admin import utc_now
from backend_app.models.payments import (
    PaymentChannelNotification,
    PaymentUnfreezeOrder,
    ProfitSharingOrder,
    ProfitSharingRuleVersionItem,
    PropertyMerchantBinding,
)
from backend_app.repositories.payments.funds import FundsRepository
from backend_app.repositories.payments.tasks import (
    TaskLease,
    complete_task,
    ensure_task,
    require_current_lease,
)


class ProfitNotificationService:
    """Preserve a receipt as corroboration and query the complete original execution."""

    def __init__(
        self, factory: sessionmaker[Session], *, clock: Callable[[], datetime] = utc_now
    ) -> None:
        self.factory = factory
        self.clock = clock

    def handle(self, lease: TaskLease) -> None:
        with self.factory() as db:
            notification = db.get(PaymentChannelNotification, lease.target_id)
            assert notification is not None
            payload = notification.payload
            number = payload.get("order_no")
            sharing = db.scalar(
                select(ProfitSharingOrder).where(ProfitSharingOrder.order_no == number)
            )
            unfreeze = db.scalar(
                select(PaymentUnfreezeOrder).where(PaymentUnfreezeOrder.order_no == number)
            )
            execution = sharing or unfreeze
            if execution is None or notification.notification_type != "profit_sharing":
                require_current_lease(db, lease, now=self.clock())
                self._finish(db, notification, lease, valid=False)
                db.commit()
                return
            repository = FundsRepository(db)
            payment = repository.lock_payment(execution.payment_order_id)
            db.refresh(execution)
            notification = db.scalars(
                select(PaymentChannelNotification)
                .where(PaymentChannelNotification.id == notification.id)
                .with_for_update(of=PaymentChannelNotification)
            ).one()
            require_current_lease(db, lease, now=self.clock())
            binding = db.get(PropertyMerchantBinding, payment.merchant_binding_id)
            assert binding is not None
            valid = (
                payload.get("service_provider_merchant_no") == binding.service_provider_merchant_no
                and payload.get("merchant_no") == binding.merchant_no
                and payload.get("channel_transaction_no") == payment.channel_transaction_no
                and payload.get("receiver_type") == "merchant"
                and bool(payload.get("channel_order_no"))
                and execution.channel_order_no in {None, payload.get("channel_order_no")}
                and notification.payment_order_id in {None, payment.id}
            )
            if sharing is not None:
                allocations = {a.id: a for a in repository.allocations(payment.id)}
                matches = []
                for item in repository.sharing_items(sharing.id):
                    rule = db.get(
                        ProfitSharingRuleVersionItem,
                        allocations[item.allocation_id].rule_version_item_id,
                    )
                    assert rule is not None
                    if rule.receiver_account == payload.get("receiver_account"):
                        matches.append(item)
                valid = (
                    valid
                    and len(matches) == 1
                    and matches[0].amount_cents == payload.get("amount_cents")
                )
                task_type = "profit_sharing_query"
            else:
                valid = (
                    valid
                    and payload.get("receiver_account") == binding.merchant_no
                    and (
                        type(payload.get("amount_cents")) is int
                        and 0 <= payload["amount_cents"] <= payment.amount_cents
                    )
                )
                task_type = "unfreeze_query"
            if valid:
                notification.payment_order_id = payment.id
                ensure_task(db, task_type, execution.id, now=self.clock(), reactivate=True)
            self._finish(db, notification, lease, valid=valid)
            db.commit()

    def _finish(
        self,
        db: Session,
        notification: PaymentChannelNotification,
        lease: TaskLease,
        *,
        valid: bool,
    ) -> None:
        if notification.status != "processed":
            notification.status = "processed" if valid else "quarantined"
            notification.processed_at = self.clock()
            notification.updated_at = self.clock()
        complete_task(db, lease, now=self.clock())
