from typing import Any

from sqlalchemy.orm import Session

from backend_app.core.config import Settings
from backend_app.core.errors import AppError
from backend_app.domain.admin.identity import AdminIdentity
from backend_app.repositories.admin import AdminRepository
from backend_app.repositories.payments.management import PaymentManagementRepository
from backend_app.schemas.mappers import payment_management as mapper
from backend_app.schemas.payments import management as schema
from backend_app.services.contracts.admin import AdminContext


class PlatformPaymentService:
    def __init__(self, db: Session, settings: Settings):
        self.db, self.settings = db, settings

    def _repo(
        self, ctx: AdminContext, permission: str, filters: dict[str, Any] | None = None
    ) -> PaymentManagementRepository:
        if ctx.scope != "platform_admin":
            raise AppError("auth.forbidden")
        identity = AdminIdentity(
            AdminRepository(self.db, "platform_admin", ctx.property_company_id)
        )
        identity.require_permission(ctx, "platform" + "." + permission)
        filters = filters if filters is not None else {}
        requested_company = filters.pop("property_company_id", None)
        return PaymentManagementRepository(self.db, requested_company)

    def payment(self, ctx: AdminContext, identifier: str) -> schema.ManagedPaymentOrder:
        repo = self._repo(ctx, "payment.read")
        item = repo.payment(identifier)
        return mapper.payment_view(self.db, item, app_id=self.settings.wechat_miniapp_app_id)

    def payments(self, ctx: AdminContext, **filters: Any) -> schema.ManagedPaymentOrderPage:
        repo = self._repo(ctx, "payment.read", filters)
        items, total = repo.payments(app_id=self.settings.wechat_miniapp_app_id, **filters)
        return schema.ManagedPaymentOrderPage(
            items=[
                mapper.payment_view(self.db, i, app_id=self.settings.wechat_miniapp_app_id)
                for i in items
            ],
            total=total,
            page=filters["page"],
            page_size=filters["page_size"],
        )

    def sharing(self, ctx: AdminContext, identifier: str) -> schema.ManagedProfitSharingOrder:
        repo = self._repo(ctx, "payment_funds.read")
        item = repo.sharing(identifier)
        return mapper.sharing_view(self.db, item)

    def sharings(self, ctx: AdminContext, **filters: Any) -> schema.ManagedProfitSharingOrderPage:
        repo = self._repo(ctx, "payment_funds.read", filters)
        items, total = repo.sharings(**filters)
        return schema.ManagedProfitSharingOrderPage(
            items=[mapper.sharing_view(self.db, i) for i in items],
            total=total,
            page=filters["page"],
            page_size=filters["page_size"],
        )

    def unfreeze(self, ctx: AdminContext, identifier: str) -> schema.ManagedUnfreezeOrder:
        repo = self._repo(ctx, "payment_funds.read")
        item = repo.unfreeze(identifier)
        return mapper.unfreeze_view(self.db, item)

    def unfreezes(self, ctx: AdminContext, **filters: Any) -> schema.ManagedUnfreezeOrderPage:
        repo = self._repo(ctx, "payment_funds.read", filters)
        items, total = repo.unfreezes(**filters)
        return schema.ManagedUnfreezeOrderPage(
            items=[mapper.unfreeze_view(self.db, i) for i in items],
            total=total,
            page=filters["page"],
            page_size=filters["page_size"],
        )

    def run(self, ctx: AdminContext, identifier: str) -> schema.ManagedReconciliationRun:
        repo = self._repo(ctx, "payment_reconciliation.read")
        item = repo.run(identifier)
        return mapper.run_view(item, company_id=repo.company_id)

    def runs(self, ctx: AdminContext, **filters: Any) -> schema.ManagedReconciliationRunPage:
        repo = self._repo(ctx, "payment_reconciliation.read", filters)
        items, total = repo.runs(**filters)
        return schema.ManagedReconciliationRunPage(
            items=[mapper.run_view(i, company_id=repo.company_id) for i in items],
            total=total,
            page=filters["page"],
            page_size=filters["page_size"],
        )

    def discrepancy(
        self, ctx: AdminContext, identifier: str
    ) -> schema.ManagedReconciliationDiscrepancy:
        repo = self._repo(ctx, "payment_reconciliation.read")
        item = repo.discrepancy(identifier)
        return mapper.discrepancy_view(self.db, item)

    def discrepancies(
        self, ctx: AdminContext, **filters: Any
    ) -> schema.ManagedReconciliationDiscrepancyPage:
        repo = self._repo(ctx, "payment_reconciliation.read", filters)
        items, total = repo.discrepancies(**filters)
        return schema.ManagedReconciliationDiscrepancyPage(
            items=[mapper.discrepancy_view(self.db, i) for i in items],
            total=total,
            page=filters["page"],
            page_size=filters["page_size"],
        )
