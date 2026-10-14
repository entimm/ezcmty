from typing import Any

from sqlalchemy.orm import Session

from backend_app.core.errors import AppError
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
