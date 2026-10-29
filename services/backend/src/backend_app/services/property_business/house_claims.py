from typing import Any

from sqlalchemy.orm import Session

from backend_app.core.errors import AppError
from backend_app.core.identifiers import new_id
from backend_app.models.house_claims import HouseClaim, ResidentHouseBinding
from backend_app.models.miniapp import MiniappUser
from backend_app.repositories.house_claims import HouseClaimRepository
from backend_app.schemas import house_claims as schema
from backend_app.schemas.mappers.house_claims import property_binding_view, property_claim_view
from backend_app.services.property_business.commands import BindingRevocation, ClaimReview
from backend_app.services.property_business.context import BusinessActor, PropertyBusinessContext


class HouseClaimUseCases:
    def __init__(self, db: Session):
        self.db = db
        self.repo = HouseClaimRepository(db)

    def _scope(
        self, ctx: PropertyBusinessContext, *permissions: str
    ) -> tuple[str, PropertyBusinessContext]:
        ctx.require(*permissions)
        return (ctx.company_id, ctx)

    def _protect(
        self, ctx: PropertyBusinessContext, *permissions: str
    ) -> tuple[BusinessActor, PropertyBusinessContext]:
        return (ctx.require(*permissions, lock=True, shared=True), ctx)

    def claims(self, ctx: PropertyBusinessContext, **filters: Any) -> schema.PropertyHouseClaimPage:
        company_id, _ = self._scope(ctx, "resident_access.read")
        items, total = self.repo.records(HouseClaim, company_id=company_id, **filters)
        return schema.PropertyHouseClaimPage(
            items=[property_claim_view(i) for i in items],
            total=total,
            page=filters["page"],
            page_size=filters["page_size"],
        )

    def get_claim(self, ctx: PropertyBusinessContext, claim_id: str) -> schema.PropertyHouseClaim:
        company_id, _ = self._scope(ctx, "resident_access.read")
        return property_claim_view(self.repo.claim(claim_id, company_id=company_id))

    def review(
        self, ctx: PropertyBusinessContext, claim_id: str, data: ClaimReview, request_id: str
    ) -> schema.PropertyHouseClaim:
        actor, identity = self._protect(ctx, "resident_access.read", "resident_access.review")
        claim = self.repo.claim(claim_id, company_id=ctx.company_id)
        self.repo.user(claim.user_id, require_enabled=data.decision == "approved")
        if data.decision == "approved":
            scope = self.repo.house(claim.house_id, lock=True)
            if not self.repo.enabled(*scope):
                raise AppError("resident.housing_unavailable")
        if claim.status != "pending" or claim.row_version != data.expected_row_version:
            raise AppError("resident.state_changed")
        if (data.decision == "rejected" or claim.match_status == "unmatched") and (not data.reason):
            raise AppError("resident.reason_required")
        claim = self.repo.transition_claim(
            claim, data.expected_row_version, data.decision, actor_id=actor.id, reason=data.reason
        )
        if data.decision == "approved":
            self.db.add(
                ResidentHouseBinding(
                    id=new_id(),
                    user_id=claim.user_id,
                    property_company_id=claim.property_company_id,
                    community_id=claim.community_id,
                    house_id=claim.house_id,
                    claim_application_id=claim.id,
                    status="active",
                    granted_at=claim.reviewed_at,
                    row_version=1,
                )
            )
            self.db.flush()
        identity.record(
            actor=actor,
            action="property.house_claim.review",
            target_type="house_claim",
            target_id=claim.id,
            request_id=request_id,
            metadata={
                "status": claim.status,
                "match_status": claim.match_status,
                "house_id": claim.house_id,
            },
        )
        return property_claim_view(claim)

    def _binding_view(self, item: ResidentHouseBinding) -> schema.PropertyHouseBinding:
        claim = self.repo.claim(item.claim_application_id, company_id=item.property_company_id)
        user = self.db.get(MiniappUser, item.user_id)
        effective = bool(
            item.status == "active"
            and user
            and user.enabled
            and self.repo.enabled(*self.repo.house(item.house_id))
        )
        return property_binding_view(item, claim, effective)

    def bindings(
        self, ctx: PropertyBusinessContext, **filters: Any
    ) -> schema.PropertyHouseBindingPage:
        company_id, _ = self._scope(ctx, "resident_access.read")
        items, total = self.repo.records(ResidentHouseBinding, company_id=company_id, **filters)
        return schema.PropertyHouseBindingPage(
            items=[self._binding_view(i) for i in items],
            total=total,
            page=filters["page"],
            page_size=filters["page_size"],
        )

    def get_binding(
        self, ctx: PropertyBusinessContext, binding_id: str
    ) -> schema.PropertyHouseBinding:
        company_id, _ = self._scope(ctx, "resident_access.read")
        return self._binding_view(self.repo.binding(binding_id, company_id=company_id))

    def revoke(
        self,
        ctx: PropertyBusinessContext,
        binding_id: str,
        data: BindingRevocation,
        request_id: str,
    ) -> schema.PropertyHouseBinding:
        actor, identity = self._protect(ctx, "resident_access.read", "resident_access.revoke")
        item = self.repo.binding(binding_id, company_id=ctx.company_id)
        self.repo.user(item.user_id)
        item = self.repo.end_binding(
            item, data.expected_row_version, "revoked", actor_id=actor.id, reason=data.reason
        )
        identity.record(
            actor=actor,
            action="property.resident_house_binding.revoke",
            target_type="resident_house_binding",
            target_id=item.id,
            request_id=request_id,
            metadata={"status": item.status, "house_id": item.house_id},
        )
        return self._binding_view(item)
