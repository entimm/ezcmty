from typing import Any

from sqlalchemy.orm import Session

from backend_app.core.errors import AppError
from backend_app.domain.billing.calculation import business_today
from backend_app.repositories.property import PropertyRepository
from backend_app.schemas import property as schema
from backend_app.schemas.mappers.property import community_view
from backend_app.services.contracts.admin import AdminContext


class PropertyWorkspaceService:
    def __init__(self, db: Session):
        self.repo = PropertyRepository(db)

    def _company_id(self, context: AdminContext, permission: str) -> str:
        if context.scope != "property_admin" or context.property_company_id is None:
            raise AppError("auth.forbidden")
        if context.must_change_password:
            raise AppError("auth.password_change_required")
        if permission not in context.permissions:
            raise AppError("auth.forbidden")
        return context.property_company_id

    def get_current_company(self, context: AdminContext) -> schema.PropertyCompany:
        company_id = self._company_id(context, "property.company.read")
        company = self.repo.company(company_id)
        if company is None or not company.enabled:
            raise AppError("auth.unauthenticated")
        return schema.PropertyCompany.model_validate(company)

    def get_summary(self, context: AdminContext) -> schema.PropertyWorkspaceSummary:
        company_id = self._company_id(context, "property.company.read")
        company = self.repo.company(company_id)
        if company is None or not company.enabled:
            raise AppError("auth.unauthenticated")
        billing_month = business_today().replace(day=1)
        values = self.repo.workspace_summary(company_id, billing_month)
        return schema.PropertyWorkspaceSummary(
            billing_month=billing_month.strftime("%Y-%m"),
            pending_house_claims=(
                values["pending_house_claims"]
                if "property.house_claim.read" in context.permissions
                else None
            ),
            monthly_receivable_cents=(
                values["monthly_receivable_cents"]
                if "property.bill.read" in context.permissions
                else None
            ),
            monthly_settled_cents=(
                values["monthly_settled_cents"]
                if "property.payment.read" in context.permissions
                else None
            ),
            pending_reconciliation_count=(
                values["pending_reconciliation_count"]
                if "property.payment_reconciliation.read" in context.permissions
                else None
            ),
        )

    def list_communities(self, context: AdminContext, **filters: Any) -> schema.CommunityPage:
        company_id = self._company_id(context, "property.community.read")
        items, total = self.repo.communities(company_scope_id=company_id, **filters)
        return schema.CommunityPage(
            items=[community_view(item, company_name) for item, company_name in items],
            total=total,
            page=filters["page"],
            page_size=filters["page_size"],
        )

    def get_community(self, context: AdminContext, community_id: str) -> schema.Community:
        company_id = self._company_id(context, "property.community.read")
        community = self.repo.community(community_id, company_scope_id=company_id)
        if community is None:
            raise AppError("resource.not_found")
        company = self.repo.company(company_id)
        if company is None or not company.enabled:
            raise AppError("auth.unauthenticated")
        return community_view(community, company.name)
