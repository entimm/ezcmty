from typing import Any

from sqlalchemy import Select, exists, select
from sqlalchemy.orm import Session

from backend_app.core.errors import AppError
from backend_app.db.base import Base
from backend_app.models.billing import Bill
from backend_app.models.payments import (
    PaymentOrder,
    PaymentOrderItem,
    PaymentReconciliationDiscrepancy,
    PaymentReconciliationRun,
    PaymentUnfreezeOrder,
    ProfitSharingOrder,
    PropertyMerchantBinding,
)
from backend_app.repositories.pagination import read_page
from backend_app.repositories.payments.orders import OrdersRepository


class PaymentManagementRepository:
    def __init__(self, db: Session, company_id: str | None = None):
        self.db, self.company_id = db, company_id

    def _payments(self) -> Select[PaymentOrder]:
        query = select(PaymentOrder)
        if self.company_id is not None:
            query = query.where(PaymentOrder.property_company_id == self.company_id)
        return query

    @staticmethod
    def _dates(filters: dict[str, Any]) -> None:
        start, end = filters.get("created_from"), filters.get("created_before")
        if any(v is not None and v.tzinfo is None for v in (start, end)):
            raise AppError("VALIDATION_ERROR")
        if start is not None and end is not None and start >= end:
            raise AppError("VALIDATION_ERROR")
        start, end = filters.get("business_date_from"), filters.get("business_date_through")
        if start is not None and end is not None and start > end:
            raise AppError("VALIDATION_ERROR")

    def _bill_filter(
        self, query: Select[PaymentOrder], filters: dict[str, Any]
    ) -> Select[PaymentOrder]:
        if filters.get("community_id") or filters.get("house_id"):
            bills = select(PaymentOrderItem.payment_order_id).join(
                Bill, Bill.id == PaymentOrderItem.bill_id
            )
            if filters.get("community_id"):
                bills = bills.where(Bill.community_id == filters["community_id"])
            if filters.get("house_id"):
                bills = bills.where(Bill.house_id == filters["house_id"])
            query = query.where(PaymentOrder.id.in_(bills))
        return query

    def payment(self, identifier: str) -> PaymentOrder:
        item = self.db.scalar(self._payments().where(PaymentOrder.id == identifier))
        if item is None:
            raise AppError("resource.not_found")
        return item

    def payments(self, *, app_id: str, **filters: Any) -> tuple[list[PaymentOrder], int]:
        self._dates(filters)
        query = self._bill_filter(self._payments(), filters)
        for name in ("status", "order_no", "channel_transaction_no"):
            if filters.get(name) is not None:
                query = query.where(getattr(PaymentOrder, name) == filters[name])
        if filters.get("created_from"):
            query = query.where(PaymentOrder.created_at >= filters["created_from"])
        if filters.get("created_before"):
            query = query.where(PaymentOrder.created_at < filters["created_before"])
        confirmation = filters.get("confirmation_status")
        if confirmation == "posted":
            query = query.where(PaymentOrder.status == "succeeded")
        elif confirmation:
            evidence = OrdersRepository.successful_evidence(app_id)
            query = query.where(
                PaymentOrder.status != "succeeded",
                evidence if confirmation == "awaiting_posting" else ~evidence,
            )
        return self._page(PaymentOrder, query, filters)

    def sharing(self, identifier: str) -> ProfitSharingOrder:
        item = self.db.get(ProfitSharingOrder, identifier)
        if item is None:
            raise AppError("resource.not_found")
        self.payment(item.payment_order_id)
        return item

    def unfreeze(self, identifier: str) -> PaymentUnfreezeOrder:
        item = self.db.get(PaymentUnfreezeOrder, identifier)
        if item is None:
            raise AppError("resource.not_found")
        self.payment(item.payment_order_id)
        return item

    def sharings(self, **filters: Any) -> tuple[list[ProfitSharingOrder], int]:
        return self._funds(ProfitSharingOrder, filters)

    def unfreezes(self, **filters: Any) -> tuple[list[PaymentUnfreezeOrder], int]:
        return self._funds(PaymentUnfreezeOrder, filters)

    def _funds[T: (ProfitSharingOrder, PaymentUnfreezeOrder)](
        self, model: type[T], filters: dict[str, Any]
    ) -> tuple[list[T], int]:
        self._dates(filters)
        parents = self._bill_filter(self._payments(), filters).with_only_columns(PaymentOrder.id)
        query = select(model).where(model.payment_order_id.in_(parents))
        for name in ("status", "order_no", "payment_order_id"):
            if filters.get(name) is not None:
                query = query.where(getattr(model, name) == filters[name])
        if filters.get("created_from"):
            query = query.where(model.created_at >= filters["created_from"])
        if filters.get("created_before"):
            query = query.where(model.created_at < filters["created_before"])
        return self._page(model, query, filters)

    def _runs(self) -> Select[PaymentReconciliationRun]:
        query = select(PaymentReconciliationRun)
        if self.company_id is not None:
            scoped = exists(
                select(PropertyMerchantBinding.id)
                .where(
                    PropertyMerchantBinding.property_company_id == self.company_id,
                    PropertyMerchantBinding.service_provider_merchant_no
                    == PaymentReconciliationRun.service_provider_merchant_no,
                    PropertyMerchantBinding.merchant_no == PaymentReconciliationRun.merchant_no,
                )
                .correlate(PaymentReconciliationRun)
            )
            query = query.where(
                PaymentReconciliationRun.statement_type != "platform_fundflow", scoped
            )
        return query

    def run(self, identifier: str) -> PaymentReconciliationRun:
        item = self.db.scalar(self._runs().where(PaymentReconciliationRun.id == identifier))
        if item is None:
            raise AppError("resource.not_found")
        return item

    def runs(self, **filters: Any) -> tuple[list[PaymentReconciliationRun], int]:
        self._dates(filters)
        query = self._runs()
        for name in ("status", "statement_type"):
            if filters.get(name) is not None:
                query = query.where(getattr(PaymentReconciliationRun, name) == filters[name])
        if filters.get("business_date_from"):
            query = query.where(
                PaymentReconciliationRun.business_date >= filters["business_date_from"]
            )
        if filters.get("business_date_through"):
            query = query.where(
                PaymentReconciliationRun.business_date <= filters["business_date_through"]
            )
        return self._page(PaymentReconciliationRun, query, filters)

    def _differences(self) -> Select[PaymentReconciliationDiscrepancy]:
        query = select(PaymentReconciliationDiscrepancy).where(
            PaymentReconciliationDiscrepancy.reconciliation_run_id.in_(
                self._runs().with_only_columns(PaymentReconciliationRun.id)
            )
        )
        if self.company_id is not None:
            query = query.where(
                PaymentReconciliationDiscrepancy.payment_order_id.in_(
                    self._payments().with_only_columns(PaymentOrder.id)
                )
            )
        return query

    def discrepancy(self, identifier: str) -> PaymentReconciliationDiscrepancy:
        item = self.db.scalar(
            self._differences().where(PaymentReconciliationDiscrepancy.id == identifier)
        )
        if item is None:
            raise AppError("resource.not_found")
        return item

    def discrepancies(self, **filters: Any) -> tuple[list[PaymentReconciliationDiscrepancy], int]:
        self._dates(filters)
        query = self._differences().join(
            PaymentReconciliationRun,
            PaymentReconciliationRun.id == PaymentReconciliationDiscrepancy.reconciliation_run_id,
        )
        for name in ("status", "difference_type", "reconciliation_run_id", "payment_order_id"):
            if filters.get(name) is not None:
                query = query.where(
                    getattr(PaymentReconciliationDiscrepancy, name) == filters[name]
                )
        if filters.get("statement_type"):
            query = query.where(
                PaymentReconciliationRun.statement_type == filters["statement_type"]
            )
        if filters.get("business_date_from"):
            query = query.where(
                PaymentReconciliationRun.business_date >= filters["business_date_from"]
            )
        if filters.get("business_date_through"):
            query = query.where(
                PaymentReconciliationRun.business_date <= filters["business_date_through"]
            )
        return self._page(PaymentReconciliationDiscrepancy, query, filters)

    def _page[T: Base](
        self, model: type[T], query: Select[T], filters: dict[str, Any]
    ) -> tuple[list[T], int]:
        descending = filters.get("sort", "-created_at,-id").startswith("-")
        return read_page(
            self.db,
            model,
            query,
            page=filters.get("page", 1),
            page_size=filters.get("page_size", 20),
            order=(("created_at", descending), ("id", descending)),
        )
