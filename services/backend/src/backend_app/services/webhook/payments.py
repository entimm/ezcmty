from collections.abc import Mapping

from sqlalchemy.orm import Session

from backend_app.integrations.wechatpay.notifications import Notifications
from backend_app.models.admin import utc_now
from backend_app.repositories.payments.channel_records import store_notification


class PaymentWebhookService:
    def __init__(self, db: Session, verifier: Notifications) -> None:
        self.db, self.verifier = db, verifier

    def receive(self, kind: str, headers: Mapping[str, str], body: bytes) -> None:
        verify = self.verifier.payment if kind == "payment" else self.verifier.profit_sharing
        notice = verify(headers, body)
        try:
            store_notification(
                self.db,
                channel_notification_id=notice.channel_notification_id,
                notification_type=notice.notification_type,
                payload=notice.payload,
                now=utc_now(),
            )
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
