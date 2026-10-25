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

    def _company_id(self, context: AdminContext, *, business: bool = False) -> str:
        if context.scope != "property_admin" or context.property_company_id is None:
            raise AppError("auth.forbidden")
        if context.must_change_password:
            raise AppError("auth.password_change_required")
        if business and not set(context.permissions).intersection(
            {
                "property.housing.read",
                "property.bill.read",
                "property.resident_access.read",
                "property.payment.read",
                "property.system.read",
            }
        ):
            raise AppError("auth.forbidden")
        return context.property_company_id

    def get_current_company(self, context: AdminContext) -> schema.PropertyCompany:
        company_id = self._company_id(context, business=True)
        company = self.repo.company(company_id)
        if company is None or not company.enabled:
            raise AppError("auth.unauthenticated")
        return schema.PropertyCompany.model_validate(company)

    def get_summary(self, context: AdminContext) -> schema.PropertyWorkspaceSummary:
        company_id = self._company_id(context)
        company = self.repo.company(company_id)
        if company is None or not company.enabled:
            raise AppError("auth.unauthenticated")
        billing_month = business_today().replace(day=1)
        values = self.repo.workspace_summary(company_id, billing_month)
        return schema.PropertyWorkspaceSummary(
            billing_month=billing_month.strftime("%Y-%m"),
            pending_house_claims=(
                values["pending_house_claims"]
                if "property.resident_access.read" in context.permissions
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
                if "property.payment.read" in context.permissions
                else None
            ),
        )

    def list_communities(self, context: AdminContext, **filters: Any) -> schema.CommunityPage:
        company_id = self._company_id(context, business=True)
        items, total = self.repo.communities(company_scope_id=company_id, **filters)
        return schema.CommunityPage(
            items=[community_view(item, company_name) for item, company_name in items],
            total=total,
            page=filters["page"],
            page_size=filters["page_size"],
        )

    def get_community(self, context: AdminContext, community_id: str) -> schema.Community:
        company_id = self._company_id(context, business=True)
        community = self.repo.community(community_id, company_scope_id=company_id)
        if community is None:
            raise AppError("resource.not_found")
        company = self.repo.company(company_id)
        if company is None or not company.enabled:
            raise AppError("auth.unauthenticated")
        return community_view(community, company.name)

    def get_context(self, context: AdminContext) -> schema.PropertyWorkspaceContext:
        company_id = self._company_id(context)
        company = self.repo.company(company_id)
        if company is None or not company.enabled:
            raise AppError("auth.unauthenticated")
        return schema.PropertyWorkspaceContext(
            property_company_id=company.id, property_company_name=company.name
        )

    def community_options(
        self,
        context: AdminContext,
        *,
        page: int,
        page_size: int,
        name: str | None,
        property_company_id: str | None,
    ) -> schema.CommunityOptionPage:
        company_id = self._company_id(context)
        items, total = self.repo.communities(
            company_scope_id=company_id,
            page=page,
            page_size=page_size,
            name=name,
            property_company_id=property_company_id,
            code=None,
            enabled=None,
            sort="-created_at",
        )
        return schema.CommunityOptionPage(
            items=[schema.CommunityOption.model_validate(item) for item, _ in items],
            total=total,
            page=page,
            page_size=page_size,
        )
