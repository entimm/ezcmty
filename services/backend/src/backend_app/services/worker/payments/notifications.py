from collections.abc import Callable
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from backend_app.integrations.wechatpay.client import WechatPayError
from backend_app.integrations.wechatpay.payments import PaymentFact
from backend_app.models.admin import utc_now
from backend_app.models.payments import PaymentChannelNotification, PaymentOrder
from backend_app.repositories.payments.tasks import TaskLease, complete_task, require_current_lease
from backend_app.services.worker.payments.confirmation import (
    ConfirmationService,
    PaymentConfirmationError,
)
from backend_app.services.worker.payments.profit_notifications import ProfitNotificationService


class NotificationService:
    def __init__(
        self,
        factory: sessionmaker[Session],
        *,
        app_id: str,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.factory, self.clock = factory, clock
        self.confirmation = ConfirmationService(factory, app_id=app_id, clock=clock)
        self.sharing = ProfitNotificationService(factory, clock=clock)

    def handle(self, lease: TaskLease) -> None:
        with self.factory() as db:
            notice = db.get(PaymentChannelNotification, lease.target_id)
            if notice is None:
                raise ValueError("Notification task has no notification")
            if notice.notification_type == "profit_sharing":
                sharing = True
                order_id, fact = None, None
            else:
                sharing = False
                order_id = db.scalar(
                    select(PaymentOrder.id).where(
                        PaymentOrder.order_no == notice.payload.get("order_no")
                    )
                )
                try:
                    fact = PaymentFact.from_snapshot(notice.payload)
                except WechatPayError:
                    fact = None
        if sharing:
            self.sharing.handle(lease)
            return
        if order_id is not None and fact is not None:
            try:
                self.confirmation.confirm(
                    order_id, fact, lease=lease, notification_id=lease.target_id
                )
                return
            except PaymentConfirmationError:
                pass
        with self.factory() as db:
            notice = db.scalars(
                select(PaymentChannelNotification)
                .where(PaymentChannelNotification.id == lease.target_id)
                .with_for_update(of=PaymentChannelNotification)
            ).one()
            now = self.clock()
            require_current_lease(db, lease, now=now)
            if notice.status == "pending":
                notice.status, notice.processed_at, notice.updated_at = "quarantined", now, now
            complete_task(db, lease, now=now)
            db.commit()
