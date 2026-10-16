from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend_app.core.errors import AppError
from backend_app.core.identifiers import new_id
from backend_app.db.errors import is_unique_violation
from backend_app.domain.admin.identity import AdminIdentity
from backend_app.models.admin import AdminAccount
from backend_app.models.house_claims import HouseClaim, ResidentHouseBinding
from backend_app.models.miniapp import MiniappUser
from backend_app.repositories.admin import AdminRepository
from backend_app.repositories.house_claims import HouseClaimRepository
from backend_app.schemas import house_claims as schema
from backend_app.schemas.mappers.house_claims import property_binding_view, property_claim_view
from backend_app.services.contracts.admin import AdminContext


class PropertyHouseClaimService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = HouseClaimRepository(db)

    def _scope(self, ctx: AdminContext, *permissions: str) -> tuple[str, AdminIdentity]:
        if ctx.property_company_id is None:
            raise AppError("auth.forbidden")
        identity = AdminIdentity(
            AdminRepository(self.db, "property_admin", ctx.property_company_id)
        )
        for code in permissions:
            identity.require_permission(ctx, code)
        return ctx.property_company_id, identity

    def _protect(self, ctx: AdminContext, *permissions: str) -> tuple[AdminAccount, AdminIdentity]:
        company_id, identity = self._scope(ctx, *permissions)
        company = self.repo.company(company_id)
        actor = self.repo.actor(company_id, ctx.account_id)
        if not company.enabled or not actor.enabled or actor.session_version != ctx.version:
            raise AppError("auth.unauthenticated")
        if actor.must_change_password:
            raise AppError("auth.password_change_required")
        if not set(permissions) <= set(identity.effective_permissions(actor.id)):
            raise AppError("auth.forbidden")
        return actor, identity

    def claims(self, ctx: AdminContext, **filters: Any) -> schema.PropertyHouseClaimPage:
        company_id, _ = self._scope(ctx, "property.house_claim.read")
        items, total = self.repo.records(HouseClaim, company_id=company_id, **filters)
        return schema.PropertyHouseClaimPage(
            items=[property_claim_view(i) for i in items],
            total=total,
            page=filters["page"],
            page_size=filters["page_size"],
        )

    def get_claim(self, ctx: AdminContext, claim_id: str) -> schema.PropertyHouseClaim:
        company_id, _ = self._scope(ctx, "property.house_claim.read")
        return property_claim_view(self.repo.claim(claim_id, company_id=company_id))

    def review(
        self, ctx: AdminContext, claim_id: str, data: schema.ClaimReview, request_id: str
    ) -> schema.PropertyHouseClaim:
        try:
            actor, identity = self._protect(
                ctx, "property.house_claim.read", "property.house_claim.review"
            )
            claim = self.repo.claim(claim_id, company_id=ctx.property_company_id)
            self.repo.user(claim.user_id, require_enabled=data.decision == "approved")
            if data.decision == "approved":
                scope = self.repo.house(claim.house_id, lock=True)
                if not self.repo.enabled(*scope):
                    raise AppError("resident.housing_unavailable")
            if claim.status != "pending" or claim.row_version != data.expected_row_version:
                raise AppError("resident.state_changed")
            if (
                data.decision == "rejected" or claim.match_status == "unmatched"
            ) and not data.reason:
                raise AppError("resident.reason_required")
            claim = self.repo.transition_claim(
                claim,
                data.expected_row_version,
                data.decision,
                actor_id=actor.id,
                reason=data.reason,
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
            identity.audit.record(
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
            self.db.commit()
            return property_claim_view(claim)
        except IntegrityError as exc:
            self.db.rollback()
            if is_unique_violation(exc, "uq_resident_binding_active") or is_unique_violation(
                exc, "uq_resident_binding_claim"
            ):
                raise AppError("resident.state_changed") from None
            raise
        except Exception:
            self.db.rollback()
            raise

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

    def bindings(self, ctx: AdminContext, **filters: Any) -> schema.PropertyHouseBindingPage:
        company_id, _ = self._scope(ctx, "property.resident_house_binding.read")
        items, total = self.repo.records(ResidentHouseBinding, company_id=company_id, **filters)
        return schema.PropertyHouseBindingPage(
            items=[self._binding_view(i) for i in items],
            total=total,
            page=filters["page"],
            page_size=filters["page_size"],
        )

    def get_binding(self, ctx: AdminContext, binding_id: str) -> schema.PropertyHouseBinding:
        company_id, _ = self._scope(ctx, "property.resident_house_binding.read")
        return self._binding_view(self.repo.binding(binding_id, company_id=company_id))

    def revoke(
        self, ctx: AdminContext, binding_id: str, data: schema.HouseRevocation, request_id: str
    ) -> schema.PropertyHouseBinding:
        try:
            actor, identity = self._protect(
                ctx,
                "property.resident_house_binding.read",
                "property.resident_house_binding.revoke",
            )
            item = self.repo.binding(binding_id, company_id=ctx.property_company_id)
            self.repo.user(item.user_id)
            item = self.repo.end_binding(
                item, data.expected_row_version, "revoked", actor_id=actor.id, reason=data.reason
            )
            identity.audit.record(
                actor=actor,
                action="property.resident_house_binding.revoke",
                target_type="resident_house_binding",
                target_id=item.id,
                request_id=request_id,
                metadata={"status": item.status, "house_id": item.house_id},
            )
            self.db.commit()
            return self._binding_view(item)
        except Exception:
            self.db.rollback()
            raise
