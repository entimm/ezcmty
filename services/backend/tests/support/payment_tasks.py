from datetime import datetime

from sqlalchemy.orm import Session, sessionmaker

from backend_app.models.payments import PaymentChannelNotification, PaymentReconciliationRun
from backend_app.repositories.payments.tasks import ensure_task


def notification_task(
    factory: sessionmaker[Session], *, now: datetime, key: str = "notification"
) -> str:
    with factory() as db:
        notice = PaymentChannelNotification(
            channel_notification_id=key,
            notification_type="payment_success",
            payload={"order_no": "PAY1"},
            status="pending",
            created_at=now,
            updated_at=now,
        )
        db.add(notice)
        db.flush()
        task = ensure_task(db, "notification_process", notice.id, now=now)
        task_id = task.id
        db.commit()
        return task_id


def reconciliation_run(factory: sessionmaker[Session], *, now: datetime) -> str:
    with factory() as db:
        run = PaymentReconciliationRun(
            business_date=now.date(),
            statement_type="platform_fundflow",
            service_provider_merchant_no="1900000001",
            merchant_no=None,
            status="ready",
            summary={},
            created_at=now,
            updated_at=now,
        )
        db.add(run)
        db.flush()
        run_id = run.id
        db.commit()
        return run_id
