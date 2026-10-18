from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import ColumnElement, and_, delete, exists, func, or_, select
from sqlalchemy.orm import Session

from backend_app.core.errors import AppError
from backend_app.models.billing import Bill
from backend_app.models.house_claims import ResidentHouseBinding
from backend_app.models.miniapp import MiniappUser
from backend_app.models.payments import (
    BillPaymentReservation,
    PaymentChannelNotification,
    PaymentChannelRequest,
    PaymentOrder,
    PaymentOrderItem,
    PropertyMerchantBinding,
)
from backend_app.models.property import PropertyCompany
from backend_app.repositories.house_claims import HouseClaimRepository
from backend_app.repositories.pagination import read_page


@dataclass(frozen=True)
class BillGuard:
    bill: Bill
    company: PropertyCompany
    payer: MiniappUser
    authorized: bool


class OrdersRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def order(
        self, order_id: str, *, user_id: str | None = None, lock: bool = False
    ) -> PaymentOrder:
        query = select(PaymentOrder).where(PaymentOrder.id == order_id)
        if user_id is not None:
            query = query.where(PaymentOrder.payer_user_id == user_id)
        if lock:
            query = query.with_for_update(of=PaymentOrder)
        order = self.db.scalar(query.execution_options(populate_existing=True))
        if order is None:
            raise AppError("resource.not_found")
        return order

    def previous(self, user_id: str, key: str) -> PaymentOrder | None:
        return self.db.scalar(
            select(PaymentOrder).where(
                PaymentOrder.payer_user_id == user_id,
                PaymentOrder.idempotency_key == key,
            )
        )

    def items(self, order_id: str) -> list[tuple[PaymentOrderItem, Bill]]:
        return [
            (row[0], row[1])
            for row in self.db.execute(
                select(PaymentOrderItem, Bill)
                .join(Bill, PaymentOrderItem.bill_id == Bill.id)
                .where(PaymentOrderItem.payment_order_id == order_id)
                .order_by(PaymentOrderItem.id)
            )
        ]

    def binding(self, order: PaymentOrder) -> PropertyMerchantBinding:
        binding = self.db.get(PropertyMerchantBinding, order.merchant_binding_id)
        if binding is None:
            raise AppError("resource.not_found")
        return binding

    def guard_bill(
        self, bill_id: str, payer_user_id: str, *, lock: bool = True, exclusive_user: bool = False
    ) -> BillGuard:
        bill = self.db.get(Bill, bill_id)
        if bill is None:
            raise AppError("resource.not_found")
        claims = HouseClaimRepository(self.db)
        if lock:
            company = claims.company(bill.property_company_id)
            payer = claims.user(payer_user_id, exclusive=exclusive_user)
        else:
            found_company = self.db.get(PropertyCompany, bill.property_company_id)
            found_payer = self.db.get(MiniappUser, payer_user_id)
            if found_company is None or found_payer is None:
                raise AppError("resource.not_found")
            company, payer = found_company, found_payer
        company, community, house, path = claims.house(bill.house_id, lock=lock)
        query = select(ResidentHouseBinding).where(
            ResidentHouseBinding.user_id == payer_user_id,
            ResidentHouseBinding.house_id == bill.house_id,
            ResidentHouseBinding.status == "active",
        )
        if lock:
            query = query.with_for_update(read=True, of=ResidentHouseBinding)
        binding = self.db.scalar(query.execution_options(populate_existing=True))
        if lock:
            bill = self.db.scalars(
                select(Bill)
                .where(Bill.id == bill_id)
                .with_for_update(of=Bill)
                .execution_options(populate_existing=True)
            ).one()
        return BillGuard(
            bill,
            company,
            payer,
            payer.enabled
            and binding is not None
            and claims.enabled(company, community, house, path),
        )

    def guard_order(
        self, order_id: str, *, user_id: str | None = None
    ) -> tuple[PaymentOrder, bool]:
        original = self.order(order_id, user_id=user_id)
        items = self.items(order_id)
        if not items:
            raise ValueError("Payment order has no bill items")
        authorized = True
        for item, _ in sorted(items, key=lambda pair: pair[0].bill_id):
            guard = self.guard_bill(item.bill_id, original.payer_user_id)
            authorized = authorized and guard.authorized
        return self.order(order_id, user_id=user_id, lock=True), authorized

    def authorized(self, order: PaymentOrder) -> bool:
        return all(
            self.guard_bill(item.bill_id, order.payer_user_id, lock=False).authorized
            for item, _ in self.items(order.id)
        )

    def reservation(self, bill_id: str) -> BillPaymentReservation | None:
        return self.db.get(BillPaymentReservation, bill_id, populate_existing=True)

    def release(self, order_id: str) -> None:
        self.db.execute(
            delete(BillPaymentReservation).where(
                BillPaymentReservation.payment_order_id == order_id
            )
        )

    @staticmethod
    def successful_evidence(app_id: str) -> ColumnElement[bool]:
        binding = (
            select(PropertyMerchantBinding.merchant_no)
            .where(PropertyMerchantBinding.id == PaymentOrder.merchant_binding_id)
            .correlate(PaymentOrder)
            .scalar_subquery()
        )
        provider = (
            select(PropertyMerchantBinding.service_provider_merchant_no)
            .where(PropertyMerchantBinding.id == PaymentOrder.merchant_binding_id)
            .correlate(PaymentOrder)
            .scalar_subquery()
        )
        payer = (
            select(
                func.encode(func.sha256(func.convert_to(MiniappUser.wechat_openid, "UTF8")), "hex")
            )
            .where(MiniappUser.id == PaymentOrder.payer_user_id)
            .correlate(PaymentOrder)
            .scalar_subquery()
        )

        def matches(data: Any) -> ColumnElement[bool]:
            return and_(
                data["channel_status"].as_string() == "SUCCESS",
                data["order_no"].as_string() == PaymentOrder.order_no,
                data["service_provider_merchant_no"].as_string() == provider,
                data["merchant_no"].as_string() == binding,
                data["app_id"].as_string() == app_id,
                data["amount_cents"].as_integer() == PaymentOrder.amount_cents,
                data["currency"].as_string() == "CNY",
                data["payer_identity_digest"].as_string() == payer,
                data["channel_transaction_no"].as_string().is_not(None),
                data["paid_at"].as_string().is_not(None),
            )

        requests = exists(
            select(PaymentChannelRequest.id)
            .where(
                PaymentChannelRequest.payment_order_id == PaymentOrder.id,
                PaymentChannelRequest.operation == "payment_query",
                PaymentChannelRequest.outcome == "verified_response",
                PaymentChannelRequest.error_code.is_(None),
                PaymentChannelRequest.finished_at.is_not(None),
                matches(PaymentChannelRequest.response_snapshot),
            )
            .correlate(PaymentOrder)
        )
        notices = exists(
            select(PaymentChannelNotification.id)
            .where(
                PaymentChannelNotification.notification_type == "payment_success",
                PaymentChannelNotification.status.in_(("pending", "processed")),
                matches(PaymentChannelNotification.payload),
            )
            .correlate(PaymentOrder)
        )
        return or_(requests, notices)

    def awaiting_posting(self, order: PaymentOrder, *, app_id: str) -> bool:
        if order.status == "succeeded":
            return False
        return bool(
            self.db.scalar(
                select(self.successful_evidence(app_id)).where(PaymentOrder.id == order.id)
            )
        )

    def list_orders(
        self,
        *,
        user_id: str,
        app_id: str,
        status: str | None = None,
        confirmation_status: str | None = None,
        idempotency_key: str | None = None,
        created_at_from: datetime | None = None,
        created_at_to: datetime | None = None,
        page: int = 1,
        page_size: int = 20,
        sort: str = "-created_at,-id",
    ) -> tuple[list[PaymentOrder], int]:
        query = select(PaymentOrder).where(PaymentOrder.payer_user_id == user_id)
        if status is not None:
            query = query.where(PaymentOrder.status == status)
        if confirmation_status == "posted":
            query = query.where(PaymentOrder.status == "succeeded")
        elif confirmation_status is not None:
            success = self.successful_evidence(app_id)
            query = query.where(
                PaymentOrder.status != "succeeded",
                success if confirmation_status == "awaiting_posting" else ~success,
            )
        if idempotency_key is not None:
            query = query.where(PaymentOrder.idempotency_key == idempotency_key)
        if created_at_from is not None:
            query = query.where(PaymentOrder.created_at >= created_at_from)
        if created_at_to is not None:
            query = query.where(PaymentOrder.created_at < created_at_to)
        return read_page(
            self.db,
            PaymentOrder,
            query,
            page=page,
            page_size=page_size,
            order=(("created_at", sort.startswith("-")), ("id", sort.startswith("-"))),
        )
