"""Property billing request and transaction adapter; shared use cases own business rules."""

import hashlib
import json
from collections.abc import Callable
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend_app.core.errors import AppError
from backend_app.db.errors import is_unique_violation
from backend_app.domain.billing import Action
from backend_app.domain.billing.basis import FeeBasisCreationCommand
from backend_app.domain.billing.creation import BillCreationCommand
from backend_app.schemas import billing as schema
from backend_app.schemas.admin import AdminSchema
from backend_app.services.contracts.admin import AdminContext
from backend_app.services.property_account_access import property_business_context
from backend_app.services.property_business import commands
from backend_app.services.property_business.billing import BillingUseCases


class PropertyBillingService:
    def __init__(self, db: Session):
        self.db = db
        self.business = BillingUseCases(db)

    def _basis[T](self, operation: Callable[[], T]) -> T:
        try:
            result = operation()
            self.db.commit()
            return result
        except IntegrityError as error:
            self.db.rollback()
            if is_unique_violation(error, "uq_fee_basis_house_version"):
                raise AppError("billing.basis_version_conflict") from error
            raise
        except Exception:
            self.db.rollback()
            raise

    def list_bases(
        self, ctx: AdminContext, community_id: str, house_id: str, **filters: Any
    ) -> schema.FeeBasisPage:
        return self.business.list_bases(
            property_business_context(self.db, ctx), community_id, house_id, **filters
        )

    def get_basis(
        self, ctx: AdminContext, community_id: str, house_id: str, version_id: str
    ) -> schema.FeeBasisVersion:
        return self.business.get_basis(
            property_business_context(self.db, ctx), community_id, house_id, version_id
        )

    def create_basis(
        self,
        ctx: AdminContext,
        community_id: str,
        house_id: str,
        data: schema.FeeBasisCreate,
        request_id: str,
    ) -> schema.FeeBasisVersion:
        return self._basis(
            lambda: self.business.create_basis(
                property_business_context(self.db, ctx),
                community_id,
                house_id,
                FeeBasisCreationCommand.from_input(
                    {
                        "house_id": house_id,
                        **data.model_dump(exclude={"expected_latest_version_no"}),
                    }
                ),
                request_id,
                expected_latest_version_no=data.expected_latest_version_no,
            )
        )

    def calculate(
        self,
        ctx: AdminContext,
        community_id: str,
        house_id: str,
        data: schema.FeeCalculationRequest,
    ) -> schema.FeeCalculation:
        return self.business.calculate(
            property_business_context(self.db, ctx), community_id, house_id, data.billing_month
        )

    def list_bills(self, ctx: AdminContext, community_id: str, **filters: Any) -> schema.BillPage:
        return self.business.list_bills(
            property_business_context(self.db, ctx), community_id, **filters
        )

    def get_bill(self, ctx: AdminContext, community_id: str, bill_id: str) -> schema.Bill:
        return self.business.get_bill(
            property_business_context(self.db, ctx), community_id, bill_id
        )

    def list_entries(
        self, ctx: AdminContext, community_id: str, bill_id: str, **filters: Any
    ) -> schema.SettlementEntryPage:
        return self.business.list_entries(
            property_business_context(self.db, ctx), community_id, bill_id, **filters
        )

    def list_operations(
        self, ctx: AdminContext, community_id: str, bill_id: str, **filters: Any
    ) -> schema.BillOperationPage:
        return self.business.list_operations(
            property_business_context(self.db, ctx), community_id, bill_id, **filters
        )

    def operation_result(self, ctx: AdminContext, key: str) -> schema.BillOperationResult:
        return self.business.operation_result(property_business_context(self.db, ctx), key)

    @staticmethod
    def _fingerprint(
        ctx: AdminContext,
        community_id: str,
        action: Action,
        bill_id: str | None,
        entry_id: str | None,
        data: AdminSchema,
    ) -> str:
        payload = [
            ctx.account_id,
            community_id,
            action,
            bill_id,
            entry_id,
            data.model_dump(mode="json", exclude_unset=action == "update"),
        ]
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        ).hexdigest()

    def write(
        self,
        ctx: AdminContext,
        community_id: str,
        action: Action,
        data: AdminSchema,
        key: str,
        request_id: str,
        *,
        bill_id: str | None = None,
        entry_id: str | None = None,
    ) -> schema.BillWriteResult:
        fingerprint = self._fingerprint(ctx, community_id, action, bill_id, entry_id, data)
        fields = frozenset(data.model_fields_set)
        try:
            context = property_business_context(self.db, ctx)
            if action == "create":
                assert isinstance(data, schema.BillCreate)
                result = self.business.create(
                    context,
                    community_id,
                    BillCreationCommand.from_input(data.model_dump(mode="json")),
                    key,
                    fingerprint,
                    request_id,
                    fields,
                )
            else:
                command: commands.BillMutation
                if isinstance(data, schema.BillUpdate):
                    command = commands.BillUpdate(
                        data.expected_row_version,
                        commands.FieldChanges(
                            data.model_dump(exclude_unset=True, exclude={"expected_row_version"})
                        ),
                        fields,
                    )
                elif isinstance(data, schema.ReceiptCreate):
                    command = commands.ReceiptCreate(
                        data.expected_row_version,
                        data.amount_cents,
                        data.received_on,
                        data.reason,
                        fields,
                    )
                elif isinstance(data, schema.ReceiptCorrection):
                    command = commands.ReceiptCorrection(
                        data.expected_row_version,
                        data.corrected_amount_cents,
                        data.corrected_received_on,
                        data.reason,
                        fields,
                    )
                else:
                    assert isinstance(data, schema.BillReasonAction)
                    command = commands.BillReasonAction(
                        data.expected_row_version, data.reason, fields
                    )
                result = self.business.write(
                    context,
                    community_id,
                    action,
                    command,
                    key,
                    request_id,
                    fingerprint,
                    bill_id=bill_id,
                    entry_id=entry_id,
                )
            self.db.commit()
            return result
        except IntegrityError as error:
            self.db.rollback()
            if is_unique_violation(error, "uq_bill_operation_key"):
                context = property_business_context(self.db, ctx)
                replay = self.business.recover_conflict(
                    context,
                    community_id,
                    action,
                    key,
                    fingerprint,
                    BillCreationCommand.from_input(data.model_dump(mode="json"))
                    if isinstance(data, schema.BillCreate)
                    else None,
                )
                if replay is not None:
                    return replay
            for constraint, code in (
                ("uq_bills_active_house_month", "billing.bill_exists"),
                ("uq_bill_entry_reversed", "billing.receipt_already_reversed"),
            ):
                if is_unique_violation(error, constraint):
                    raise AppError(code) from error
            raise
        except Exception:
            self.db.rollback()
            raise
