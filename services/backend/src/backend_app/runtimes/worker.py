import signal
from threading import Event

from sqlalchemy.orm import Session, sessionmaker

from backend_app.core.config import Settings, get_settings
from backend_app.core.logging import configure_logging
from backend_app.db.session import get_session_factory
from backend_app.integrations.wechatpay.client import WechatPayClient
from backend_app.integrations.wechatpay.payments import Payments
from backend_app.integrations.wechatpay.profit_sharing import ProfitSharing
from backend_app.integrations.wechatpay.statements import Statements
from backend_app.services.worker.payments.notifications import NotificationService
from backend_app.services.worker.payments.orders import OrderService
from backend_app.services.worker.payments.profit_sharing import ProfitSharingService
from backend_app.services.worker.payments.reconciliation import ReconciliationService
from backend_app.services.worker.payments.unfreezing import UnfreezingService
from backend_app.tasks.handlers.payments import PaymentHandlers
from backend_app.tasks.runner import run_worker


def build_handlers(factory: sessionmaker[Session], settings: Settings) -> PaymentHandlers:
    # Missing merchant material blocks channel calls while durable local recovery keeps running.
    client = WechatPayClient.from_settings(settings, lazy=True)
    sharing_channel = ProfitSharing(client)
    orders = OrderService(factory, settings, Payments(client), sharing_channel)
    notices = NotificationService(factory, app_id=settings.wechat_miniapp_app_id)
    sharing = ProfitSharingService(factory, sharing_channel)
    unfreezing = UnfreezingService(factory, sharing_channel)
    reconciliation = ReconciliationService(
        factory,
        Statements(client),
        service_provider_merchant_no=settings.wechatpay_service_provider_merchant_no,
        app_id=settings.wechat_miniapp_app_id,
    )

    def scan_orders() -> None:
        orders.scan()

    def produce_reconciliations() -> None:
        reconciliation.scan()

    return PaymentHandlers(
        tasks={
            "payment_submit": orders.handle,
            "payment_query": orders.handle,
            "payment_close": orders.handle,
            "notification_process": notices.handle,
            "profit_sharing_submit": sharing.handle,
            "profit_sharing_query": sharing.handle,
            "unfreeze_submit": unfreezing.handle,
            "unfreeze_query": unfreezing.handle,
            "reconciliation": reconciliation.handle,
        },
        periodic_checks={
            "payment_authorizations": scan_orders,
            "daily_reconciliation": produce_reconciliations,
        },
    )


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, "worker")
    stop_event = Event()
    signal.signal(signal.SIGINT, lambda *_: stop_event.set())
    signal.signal(signal.SIGTERM, lambda *_: stop_event.set())
    factory = get_session_factory()
    run_worker(stop_event, factory=factory, handlers=build_handlers(factory, settings))


if __name__ == "__main__":
    main()
