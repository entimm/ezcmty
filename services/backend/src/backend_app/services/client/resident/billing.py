from typing import Any

from sqlalchemy.orm import Session

from backend_app.core.config import Settings
from backend_app.core.errors import AppError
from backend_app.domain.billing import business_today
from backend_app.domain.client.types import ClientAuthorization
from backend_app.models.billing import Bill
from backend_app.repositories.miniapp import MiniappRepository
from backend_app.repositories.payments.billing import ResidentBillingRepository
from backend_app.repositories.payments.configuration import ConfigurationRepository
from backend_app.schemas.mappers.payment_configuration import configuration_view
from backend_app.schemas.payments import resident_billing as schema


class ResidentBillingService:
    def __init__(self, db: Session, settings: Settings):
        self.db = db
        self.repo = ResidentBillingRepository(db)
        self.identity = MiniappRepository(db)
        self.settings = settings

    def _view(
        self,
        user_id: str,
        bill: Bill,
        reservations: dict[str, tuple[str, str]],
        *,
        ready: bool,
        company_name: str,
    ) -> schema.ResidentBill:
        availability = "available"
        own_id = None
        reservation = reservations.get(bill.id)
        if bill.lifecycle_status == "voided":
            availability = "voided"
        elif bill.outstanding_cents == 0:
            availability = "settled"
        elif reservation:
            order_id, payer = reservation
            availability = (
                "own_payment_in_progress" if payer == user_id else "other_payment_in_progress"
            )
            own_id = order_id if payer == user_id else None
        elif not ready or not self.settings.payment_new_orders_enabled:
            availability = "collection_unavailable"
        settlement = (
            None
            if bill.lifecycle_status == "voided"
            else "settled"
            if bill.outstanding_cents == 0
            else "partially_settled"
            if bill.settled_cents
            else "unpaid"
        )
        return schema.ResidentBill.model_validate(
            {
                "id": bill.id,
                "property_company_id": bill.property_company_id,
                "property_company_name": company_name,
                "community_id": bill.community_id,
                "house_id": bill.house_id,
                "house_label_snapshot": bill.house_label_snapshot,
                "bill_type": "property_fee",
                "billing_month": bill.period_start.strftime("%Y-%m"),
                "period_start": bill.period_start,
                "period_end": bill.period_end,
                "receivable_cents": bill.receivable_cents,
                "settled_cents": bill.settled_cents,
                "outstanding_cents": bill.outstanding_cents,
                "lifecycle_status": bill.lifecycle_status,
                "settlement_status": settlement,
                "due_date": bill.due_date,
                "is_overdue": bill.lifecycle_status == "active"
                and bill.outstanding_cents > 0
                and bill.due_date is not None
                and bill.due_date < business_today(),
                "row_version": bill.row_version,
                "payment_availability": availability,
                "own_payment_order_id": own_id,
                "created_at": bill.created_at,
                "updated_at": bill.updated_at,
            }
        )

    def get(self, ctx: ClientAuthorization, bill_id: str) -> schema.ResidentBill:
        self.identity.user(ctx.user_id, ctx.version)
        bill = self.repo.bill(ctx.user_id, bill_id)
        repo = ConfigurationRepository(self.db)
        ready = configuration_view(repo, bill.property_company_id, self.settings).ready
        return self._view(
            ctx.user_id,
            bill,
            self.repo.reservations([bill.id]),
            ready=ready,
            company_name=repo.company(bill.property_company_id).name,
        )

    def list(
        self, ctx: ClientAuthorization, binding_id: str, **filters: Any
    ) -> schema.ResidentBillPage:
        self.identity.user(ctx.user_id, ctx.version)
        start, end = filters["billing_month_from"], filters["billing_month_to"]
        if start and end and start > end:
            raise AppError("VALIDATION_ERROR")
        house_id = self.repo.binding_house(ctx.user_id, binding_id)
        items, total = self.repo.bills(house_id, **filters)
        company, _, _, _ = self.repo.housing.house(house_id)
        ready = configuration_view(
            ConfigurationRepository(self.db), company.id, self.settings
        ).ready
        reservations = self.repo.reservations([i.id for i in items])
        return schema.ResidentBillPage(
            items=[
                self._view(ctx.user_id, i, reservations, ready=ready, company_name=company.name)
                for i in items
            ],
            total=total,
            page=filters["page"],
            page_size=filters["page_size"],
        )

    def entries(
        self, ctx: ClientAuthorization, bill_id: str, **filters: Any
    ) -> schema.ResidentBillSettlementEntryPage:
        self.identity.user(ctx.user_id, ctx.version)
        self.repo.bill(ctx.user_id, bill_id)
        items, total = self.repo.entries(bill_id, **filters)
        own = self.repo.own_payments(
            ctx.user_id, [i.payment_order_item_id for i in items if i.payment_order_item_id]
        )
        return schema.ResidentBillSettlementEntryPage.model_validate(
            {
                "items": [
                    {
                        "id": i.id,
                        "bill_id": i.bill_id,
                        "entry_type": i.entry_type,
                        "source_type": i.source_type,
                        "amount_cents": i.amount_cents,
                        "received_on": i.received_on,
                        "display_type": "own_payment"
                        if i.payment_order_item_id in own
                        else "other_payment"
                        if i.source_type == "online_payment"
                        else "offline_adjustment"
                        if i.entry_type == "reversal"
                        else "offline_receipt",
                        "own_payment_order_id": own.get(i.payment_order_item_id)
                        if i.payment_order_item_id
                        else None,
                        "created_at": i.created_at,
                    }
                    for i in items
                ],
                "total": total,
                "page": filters["page"],
                "page_size": filters["page_size"],
            }
        )
