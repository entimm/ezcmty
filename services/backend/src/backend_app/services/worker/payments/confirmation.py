"""The single application use case that turns durable trusted payment evidence into receipts."""

from collections.abc import Callable
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from backend_app.domain.billing.posting import post_online_receipt
from backend_app.integrations.wechatpay.client import identity_digest
from backend_app.integrations.wechatpay.payments import PaymentFact
from backend_app.models.admin import utc_now
from backend_app.models.miniapp import MiniappUser
from backend_app.models.payments import (
    BillPaymentReservation,
    PaymentChannelNotification,
    PaymentChannelRequest,
    PaymentOrder,
    PaymentOrderItem,
    PropertyMerchantBinding,
)
from backend_app.repositories.billing import BillingRepository
from backend_app.repositories.payments.funds import FundsRepository
from backend_app.repositories.payments.tasks import (
    TaskLease,
    complete_task,
    require_current_lease,
)


class PaymentConfirmationError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def verify_payment_fact(
    order: PaymentOrder,
    binding: PropertyMerchantBinding,
    payer: MiniappUser,
    fact: PaymentFact,
    *,
    app_id: str,
) -> None:
    """Verify historical identity, independent of current authorizations and enabled states."""
    if (
        fact.channel_status != "SUCCESS"
        or fact.service_provider_merchant_no != binding.service_provider_merchant_no
        or fact.merchant_no != binding.merchant_no
        or fact.app_id != app_id
        or fact.order_no != order.order_no
        or fact.amount_cents != order.amount_cents
        or fact.currency != "CNY"
        or fact.payer_identity_digest != identity_digest(payer.wechat_openid)
        or not fact.channel_transaction_no
        or fact.paid_at is None
        or fact.paid_at.utcoffset() is None
        or (fact.payer_total_cents is not None and fact.payer_total_cents < 0)
    ):
        raise PaymentConfirmationError("PAYMENT_FACT_MISMATCH")
    if order.status == "succeeded" and (
        order.channel_transaction_no != fact.channel_transaction_no
        or order.paid_at != fact.paid_at
        or order.payer_total_cents != fact.payer_total_cents
    ):
        raise PaymentConfirmationError("PAYMENT_CONFIRMATION_CONFLICT")


def _require_persisted_source(
    db: Session,
    order_id: str,
    fact: PaymentFact,
    *,
    source_request_id: str | None,
    notification_id: str | None,
) -> PaymentChannelNotification | None:
    if (source_request_id is None) == (notification_id is None):
        raise PaymentConfirmationError("PAYMENT_EVIDENCE_REQUIRED")
    snapshot = fact.snapshot()
    if source_request_id is not None:
        record = db.get(PaymentChannelRequest, source_request_id)
        if (
            record is None
            or record.payment_order_id != order_id
            or record.operation != "payment_query"
            or record.outcome != "verified_response"
            or record.finished_at is None
            or record.response_snapshot != snapshot
        ):
            raise PaymentConfirmationError("PAYMENT_EVIDENCE_MISMATCH")
        return None
    notification = db.get(PaymentChannelNotification, notification_id)
    if (
        notification is None
        or notification.notification_type != "payment_success"
        or notification.status not in {"pending", "quarantined", "processed"}
        or notification.payment_order_id not in {None, order_id}
        or notification.payload != snapshot
    ):
        raise PaymentConfirmationError("PAYMENT_EVIDENCE_MISMATCH")
    return notification


class ConfirmationService:
    def __init__(
        self,
        factory: sessionmaker[Session],
        *,
        app_id: str,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.factory = factory
        self.app_id = app_id
        self.clock = clock

    def confirm(
        self,
        payment_order_id: str,
        fact: PaymentFact,
        *,
        lease: TaskLease | None = None,
        source_request_id: str | None = None,
        notification_id: str | None = None,
    ) -> bool:
        with self.factory() as db:
            posted = self.apply_confirmed_payment(
                db,
                payment_order_id,
                fact,
                lease=lease,
                source_request_id=source_request_id,
                notification_id=notification_id,
            )
            db.commit()
            return posted

    def apply_confirmed_payment(
        self,
        db: Session,
        payment_order_id: str,
        fact: PaymentFact,
        *,
        lease: TaskLease | None = None,
        source_request_id: str | None = None,
        notification_id: str | None = None,
    ) -> bool:
        """Apply within a caller transaction; never commit partial payment/accounting facts."""
        original = db.get(PaymentOrder, payment_order_id)
        if original is None:
            raise PaymentConfirmationError("PAYMENT_ORDER_NOT_FOUND")
        items = list(
            db.scalars(
                select(PaymentOrderItem)
                .where(PaymentOrderItem.payment_order_id == original.id)
                .order_by(PaymentOrderItem.bill_id)
            )
        )
        if not items:
            raise PaymentConfirmationError("PAYMENT_ITEMS_MISSING")
        billing = BillingRepository(db, original.property_company_id)
        if billing.protect_company() is None:
            raise PaymentConfirmationError("PAYMENT_COMPANY_NOT_FOUND")
        bills = billing.protect_bill_resources([item.bill_id for item in items])
        if len(bills) != len(items):
            raise PaymentConfirmationError("PAYMENT_BILLS_MISSING")
        funds = FundsRepository(db)
        order = funds.lock_payment(payment_order_id)
        now = self.clock()
        if lease is not None:
            expected = notification_id if lease.task_type == "notification_process" else order.id
            if lease.target_id != expected or lease.task_type not in {
                "payment_submit",
                "payment_query",
                "payment_close",
                "notification_process",
            }:
                raise PaymentConfirmationError("PAYMENT_TASK_TARGET_MISMATCH")
            require_current_lease(db, lease, now=now)
        notification = _require_persisted_source(
            db,
            order.id,
            fact,
            source_request_id=source_request_id,
            notification_id=notification_id,
        )
        binding = db.get(PropertyMerchantBinding, order.merchant_binding_id)
        payer = db.get(MiniappUser, order.payer_user_id)
        if binding is None or payer is None:
            raise PaymentConfirmationError("PAYMENT_IDENTITY_MISSING")
        verify_payment_fact(order, binding, payer, fact, app_id=self.app_id)
        if order.status == "closed":
            raise PaymentConfirmationError("PAYMENT_ALREADY_CLOSED")
        posted = order.status != "succeeded"
        if posted:
            by_id = {bill.id: bill for bill in bills}
            for item in items:
                reservation = billing.reservation(item.bill_id)
                if reservation is None or reservation.payment_order_id != order.id:
                    raise PaymentConfirmationError("PAYMENT_RESERVATION_MISMATCH")
                if by_id[item.bill_id].outstanding_cents != item.amount_cents:
                    raise PaymentConfirmationError("PAYMENT_BILL_BALANCE_MISMATCH")
            order.status = "succeeded"
            order.channel_transaction_no = fact.channel_transaction_no
            order.paid_at = fact.paid_at
            order.payer_total_cents = fact.payer_total_cents
            order.prepay_token = None
            order.updated_at = now
            db.flush()
            assert order.paid_at is not None
            request_id = lease.id if lease is not None else source_request_id or notification_id
            assert request_id is not None
            for item in items:
                post_online_receipt(billing, by_id[item.bill_id], item, order.paid_at, request_id)
            funds.initialize_funds(order, now=now)
            db.flush()
            for item in items:
                db.execute(
                    delete(BillPaymentReservation).where(
                        BillPaymentReservation.bill_id == item.bill_id,
                        BillPaymentReservation.payment_order_id == order.id,
                    )
                )
        if notification is not None and notification.status != "processed":
            notification.payment_order_id = order.id
            notification.status = "processed"
            notification.processed_at = now
            notification.updated_at = now
        if lease is not None:
            complete_task(db, lease, now=now)
        db.flush()
        return posted
