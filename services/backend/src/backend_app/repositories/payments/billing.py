from sqlalchemy import select
from sqlalchemy.orm import Session

from backend_app.core.errors import AppError
from backend_app.models.billing import Bill, BillSettlementEntry
from backend_app.models.payments import BillPaymentReservation, PaymentOrder, PaymentOrderItem
from backend_app.repositories.house_claims import HouseClaimRepository
from backend_app.repositories.pagination import read_page


class ResidentBillingRepository:
    def __init__(self, db: Session):
        self.db = db
        self.housing = HouseClaimRepository(db)

    def authorized_house(self, user_id: str, house_id: str) -> None:
        if self.housing.active_binding(user_id, house_id) is None:
            raise AppError("resource.not_found")
        if not self.housing.enabled(*self.housing.house(house_id)):
            raise AppError("resource.not_found")

    def binding_house(self, user_id: str, binding_id: str) -> str:
        binding = self.housing.binding(binding_id, user_id=user_id)
        if binding.status != "active":
            raise AppError("resource.not_found")
        self.authorized_house(user_id, binding.house_id)
        return binding.house_id

    def bill(self, user_id: str, bill_id: str) -> Bill:
        bill = self.db.get(Bill, bill_id)
        if bill is None:
            raise AppError("resource.not_found")
        self.authorized_house(user_id, bill.house_id)
        return bill

    def bills(
        self,
        house_id: str,
        *,
        scope: str,
        billing_month_from: str | None,
        billing_month_to: str | None,
        page: int,
        page_size: int,
        sort: str,
    ) -> tuple[list[Bill], int]:
        query = select(Bill).where(Bill.house_id == house_id)
        if scope == "outstanding":
            query = query.where(Bill.lifecycle_status == "active", Bill.outstanding_cents > 0)
        if billing_month_from:
            query = query.where(Bill.period_start >= billing_month_from + "-01")
        if billing_month_to:
            query = query.where(Bill.period_start <= billing_month_to + "-01")
        return read_page(
            self.db,
            Bill,
            query,
            page=page,
            page_size=page_size,
            order=(("period_start", sort.startswith("-")), ("id", sort.startswith("-"))),
        )

    def reservations(self, bill_ids: list[str]) -> dict[str, tuple[str, str]]:
        rows = self.db.execute(
            select(BillPaymentReservation.bill_id, PaymentOrder.id, PaymentOrder.payer_user_id)
            .join(PaymentOrder, PaymentOrder.id == BillPaymentReservation.payment_order_id)
            .where(BillPaymentReservation.bill_id.in_(bill_ids))
        ).all()
        return {bill_id: (order_id, payer_id) for bill_id, order_id, payer_id in rows}

    def entries(
        self, bill_id: str, *, page: int, page_size: int, sort: str
    ) -> tuple[list[BillSettlementEntry], int]:
        return read_page(
            self.db,
            BillSettlementEntry,
            select(BillSettlementEntry).where(BillSettlementEntry.bill_id == bill_id),
            page=page,
            page_size=page_size,
            order=(("created_at", sort.startswith("-")), ("id", sort.startswith("-"))),
        )

    def own_payments(self, user_id: str, item_ids: list[str]) -> dict[str, str]:
        return dict(
            self.db.execute(
                select(PaymentOrderItem.id, PaymentOrder.id)
                .join(PaymentOrder, PaymentOrder.id == PaymentOrderItem.payment_order_id)
                .where(PaymentOrderItem.id.in_(item_ids), PaymentOrder.payer_user_id == user_id)
            ).all()
        )
