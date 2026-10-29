"""Property identity, request and transaction adapter for resident access."""

from collections.abc import Callable
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend_app.core.errors import AppError
from backend_app.db.errors import is_unique_violation
from backend_app.schemas import house_claims as schema
from backend_app.services.contracts.admin import AdminContext
from backend_app.services.property_account_access import property_business_context
from backend_app.services.property_business.commands import BindingRevocation, ClaimReview
from backend_app.services.property_business.house_claims import HouseClaimUseCases


class PropertyHouseClaimService:
    def __init__(self, db: Session):
        self.db = db
        self.business = HouseClaimUseCases(db)

    def _write[T](self, operation: Callable[[], T]) -> T:
        try:
            result = operation()
            self.db.commit()
            return result
        except IntegrityError as error:
            self.db.rollback()
            if is_unique_violation(error, "uq_resident_binding_active") or is_unique_violation(
                error, "uq_resident_binding_claim"
            ):
                raise AppError("resident.state_changed") from None
            raise
        except Exception:
            self.db.rollback()
            raise

    def claims(self, ctx: AdminContext, **filters: Any) -> schema.PropertyHouseClaimPage:
        return self.business.claims(property_business_context(self.db, ctx), **filters)

    def get_claim(self, ctx: AdminContext, claim_id: str) -> schema.PropertyHouseClaim:
        return self.business.get_claim(property_business_context(self.db, ctx), claim_id)

    def review(
        self, ctx: AdminContext, claim_id: str, data: schema.ClaimReview, request_id: str
    ) -> schema.PropertyHouseClaim:
        return self._write(
            lambda: self.business.review(
                property_business_context(self.db, ctx),
                claim_id,
                ClaimReview(data.expected_row_version, data.decision, data.reason),
                request_id,
            )
        )

    def bindings(self, ctx: AdminContext, **filters: Any) -> schema.PropertyHouseBindingPage:
        return self.business.bindings(property_business_context(self.db, ctx), **filters)

    def get_binding(self, ctx: AdminContext, binding_id: str) -> schema.PropertyHouseBinding:
        return self.business.get_binding(property_business_context(self.db, ctx), binding_id)

    def revoke(
        self, ctx: AdminContext, binding_id: str, data: schema.HouseRevocation, request_id: str
    ) -> schema.PropertyHouseBinding:
        return self._write(
            lambda: self.business.revoke(
                property_business_context(self.db, ctx),
                binding_id,
                BindingRevocation(data.expected_row_version, data.reason),
                request_id,
            )
        )
