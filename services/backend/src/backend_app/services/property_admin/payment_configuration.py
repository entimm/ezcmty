from typing import Any

from sqlalchemy.orm import Session

from backend_app.core.config import Settings
from backend_app.core.errors import AppError
from backend_app.domain.admin.identity import AdminIdentity
from backend_app.repositories.admin import AdminRepository
from backend_app.repositories.payments.configuration import ConfigurationRepository
from backend_app.schemas.mappers.payment_configuration import configuration_view, rule_view
from backend_app.schemas.payments import configuration as schema
from backend_app.services.contracts.admin import AdminContext


class PropertyPaymentConfigurationService:
    def __init__(self, db: Session, settings: Settings):
        self.db = db
        self.repo = ConfigurationRepository(db)
        self.settings = settings

    def _company(self, ctx: AdminContext) -> str:
        if ctx.scope != "property_admin" or ctx.property_company_id is None:
            raise AppError("auth.forbidden")
        identity = AdminIdentity(
            AdminRepository(self.db, "property_admin", ctx.property_company_id)
        )
        identity.require_permission(ctx, "property.payment_config.read")
        company = self.repo.company(ctx.property_company_id)
        if not company.enabled:
            raise AppError("auth.unauthenticated")
        return company.id

    def get(self, ctx: AdminContext) -> schema.PaymentConfiguration:
        return configuration_view(self.repo, self._company(ctx), self.settings)

    def bindings(self, ctx: AdminContext, **filters: Any) -> schema.MerchantBindingPage:
        items, total = self.repo.binding_page(self._company(ctx), **filters)
        return schema.MerchantBindingPage(
            items=[schema.MerchantBinding.model_validate(i) for i in items],
            total=total,
            page=filters["page"],
            page_size=filters["page_size"],
        )

    def rules(self, ctx: AdminContext, **filters: Any) -> schema.ProfitSharingRuleVersionPage:
        items, total = self.repo.rule_page(self._company(ctx), **filters)
        return schema.ProfitSharingRuleVersionPage(
            items=[rule_view(self.repo, i) for i in items],
            total=total,
            page=filters["page"],
            page_size=filters["page_size"],
        )

    def rule(self, ctx: AdminContext, version_id: str) -> schema.ProfitSharingRuleVersion:
        return rule_view(self.repo, self.repo.rule(self._company(ctx), version_id))
