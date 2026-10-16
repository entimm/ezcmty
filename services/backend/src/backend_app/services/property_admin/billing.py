import hashlib
import json
from datetime import date
from decimal import Decimal
from typing import Any, cast

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend_app.core.errors import AppError
from backend_app.core.identifiers import new_id
from backend_app.db.errors import is_unique_violation
from backend_app.domain.admin.identity import AdminIdentity
from backend_app.domain.billing import (
    RULE_VERSION,
    Action,
    business_today,
    calculate_amount,
    month_date,
    next_month,
)
from backend_app.models.admin import AdminAccount, utc_now
from backend_app.models.billing import Bill, BillOperation, BillSettlementEntry, FeeBasisVersion
from backend_app.models.housing import House, SpaceNode
from backend_app.models.property import Community
from backend_app.repositories.admin import AdminRepository
from backend_app.repositories.billing import BillingRepository
from backend_app.schemas import billing as schema
from backend_app.schemas.admin import AdminSchema
from backend_app.schemas.mappers.billing import basis_view, bill_view, entry_view, operation_view
from backend_app.services.contracts.admin import AdminContext

PERMISSIONS: dict[Action, str] = {
    "create": "property.bill.create",
    "update": "property.bill.update",
    "receipt": "property.bill_receipt.create",
    "correct_receipt": "property.bill_receipt.correct",
    "reverse_receipt": "property.bill_receipt.correct",
    "void": "property.bill.void",
}


class PropertyBillingService:
    def __init__(self, db: Session):
        self.db = db

    def _scope(self, ctx: AdminContext, permission: str) -> tuple[BillingRepository, AdminIdentity]:
        identity = AdminIdentity(
            AdminRepository(self.db, "property_admin", ctx.property_company_id)
        )
        identity.require_permission(ctx, permission)
        if ctx.property_company_id is None:
            raise AppError("auth.forbidden")
        return BillingRepository(self.db, ctx.property_company_id), identity

    def _protect(
        self, ctx: AdminContext, permission: str, community_id: str | None
    ) -> tuple[BillingRepository, AdminIdentity, AdminAccount, Community | None]:
        repo, identity = self._scope(ctx, permission)
        company, actor, community = repo.protect(ctx.account_id, community_id)
        if (
            company is None
            or not company.enabled
            or actor is None
            or not actor.enabled
            or actor.session_version != ctx.version
        ):
            raise AppError("auth.unauthenticated")
        if actor.must_change_password:
            raise AppError("auth.password_change_required")
        if permission not in identity.effective_permissions(actor.id):
            raise AppError("auth.forbidden")
        if community_id is not None and community is None:
            raise AppError("resource.not_found")
        return repo, identity, actor, community

    def _community(self, repo: BillingRepository, community_id: str) -> Community:
        item = repo.community(community_id)
        if item is None:
            raise AppError("resource.not_found")
        return item

    def _house(
        self,
        repo: BillingRepository,
        community: Community,
        house_id: str,
        *,
        lock: bool = False,
        exclusive: bool = False,
    ) -> tuple[House, list[SpaceNode]]:
        house, path = repo.house(community.id, house_id, lock=lock, exclusive=exclusive)
        if house is None or not path:
            raise AppError("resource.not_found")
        return house, path

    @staticmethod
    def _enabled(community: Community, house: House, path: list[SpaceNode]) -> bool:
        return community.enabled and house.enabled and bool(path) and all(n.enabled for n in path)

    def _require_enabled(self, community: Community, house: House, path: list[SpaceNode]) -> None:
        if not self._enabled(community, house, path):
            raise AppError("property.housing_disabled")

    @staticmethod
    def _label(community: Community, house: House, path: list[SpaceNode]) -> str:
        label = "／".join([community.name, *(n.name for n in path), house.room_no])
        if len(label) > 512:
            raise AppError("billing.house_label_too_long")
        return label

    def list_bases(
        self, ctx: AdminContext, community_id: str, house_id: str, **filters: Any
    ) -> schema.FeeBasisPage:
        repo, _ = self._scope(ctx, "property.fee_basis.read")
        self._house(repo, self._community(repo, community_id), house_id)
        items, total = repo.bases(house_id, **filters)
        return schema.FeeBasisPage(items=[basis_view(i) for i in items], total=total, **filters)

    def get_basis(
        self, ctx: AdminContext, community_id: str, house_id: str, version_id: str
    ) -> schema.FeeBasisVersion:
        repo, _ = self._scope(ctx, "property.fee_basis.read")
        self._house(repo, self._community(repo, community_id), house_id)
        item = repo.basis(house_id, version_id)
        if item is None:
            raise AppError("resource.not_found")
        return basis_view(item)

    def create_basis(
        self,
        ctx: AdminContext,
        community_id: str,
        house_id: str,
        data: schema.FeeBasisCreate,
        request_id: str,
    ) -> schema.FeeBasisVersion:
        try:
            repo, identity, actor, community = self._protect(
                ctx, "property.fee_basis.create", community_id
            )
            assert community
            house, path = self._house(repo, community, house_id, lock=True, exclusive=True)
            self._require_enabled(community, house, path)
            number = repo.latest_basis_number(house_id)
            if number != data.expected_latest_version_no:
                raise AppError("billing.basis_version_conflict")
            item = FeeBasisVersion(
                id=new_id(),
                house_id=house_id,
                version_no=number + 1,
                effective_from_month=month_date(data.effective_from_month),
                house_usage=data.house_usage,
                area_sqm=Decimal(data.area_sqm) if data.area_sqm is not None else None,
                unit_price_cents=data.unit_price_cents,
                fixed_amount_cents=data.fixed_amount_cents,
                change_reason=data.change_reason,
                created_by=actor.id,
                created_at=utc_now(),
            )
            self.db.add(item)
            identity.audit.record(
                actor=actor,
                action="property.fee_basis.create",
                target_type="fee_basis_version",
                target_id=item.id,
                request_id=request_id,
                metadata={
                    "house_id": house_id,
                    "version_no": item.version_no,
                    "effective_from_month": data.effective_from_month,
                },
            )
            self.db.commit()
            return basis_view(item)
        except IntegrityError as exc:
            self.db.rollback()
            if is_unique_violation(exc, "uq_fee_basis_house_version"):
                raise AppError("billing.basis_version_conflict") from exc
            raise
        except Exception:
            self.db.rollback()
            raise

    def calculate(
        self,
        ctx: AdminContext,
        community_id: str,
        house_id: str,
        data: schema.FeeCalculationRequest,
    ) -> schema.FeeCalculation:
        repo, _ = self._scope(ctx, "property.fee_basis.read")
        community = self._community(repo, community_id)
        house, path = self._house(repo, community, house_id)
        start = month_date(data.billing_month)
        basis = repo.effective_basis(house_id, start)
        return schema.FeeCalculation(
            available=basis is not None,
            billing_month=data.billing_month,
            period_start=start,
            period_end=next_month(start),
            house_label_snapshot=self._label(community, house, path),
            basis=basis_view(basis) if basis else None,
            calculation_method=("fixed" if basis.fixed_amount_cents is not None else "area_rate")
            if basis
            else None,
            calculation_rule_version=RULE_VERSION if basis else None,
            receivable_cents=calculate_amount(
                basis.area_sqm, basis.unit_price_cents, basis.fixed_amount_cents
            )
            if basis
            else None,
        )

    def _bill_views(
        self,
        repo: BillingRepository,
        community: Community,
        items: list[Bill],
        *,
        today: date | None = None,
    ) -> list[schema.Bill]:
        if today is None:
            today = business_today()
        bases = repo.basis_map([i.basis_version_id for i in items if i.basis_version_id])
        states = repo.house_states(community, [i.house_id for i in items])
        return [
            bill_view(i, bases.get(i.basis_version_id or ""), states.get(i.house_id, False), today)
            for i in items
        ]

    def list_bills(self, ctx: AdminContext, community_id: str, **filters: Any) -> schema.BillPage:
        repo, _ = self._scope(ctx, "property.bill.read")
        community = self._community(repo, community_id)
        today = business_today()
        items, total = repo.bill_list(community_id, today=today, **filters)
        return schema.BillPage(
            items=self._bill_views(repo, community, items, today=today),
            total=total,
            page=filters["page"],
            page_size=filters["page_size"],
        )

    def get_bill(self, ctx: AdminContext, community_id: str, bill_id: str) -> schema.Bill:
        repo, _ = self._scope(ctx, "property.bill.read")
        community = self._community(repo, community_id)
        item = repo.bill(community_id, bill_id)
        if item is None:
            raise AppError("resource.not_found")
        return self._bill_views(repo, community, [item])[0]

    def list_entries(
        self, ctx: AdminContext, community_id: str, bill_id: str, **filters: Any
    ) -> schema.SettlementEntryPage:
        repo, _ = self._scope(ctx, "property.bill.read")
        if repo.bill(community_id, bill_id) is None:
            raise AppError("resource.not_found")
        items, total = repo.entries(bill_id, **filters)
        operations = repo.operation_map([i.operation_id for i in items])
        names = repo.actor_names([i.actor_id for i in operations.values()])
        reversed_by = repo.reversals([i.id for i in items])
        return schema.SettlementEntryPage(
            items=[
                entry_view(
                    i,
                    operations[i.operation_id],
                    names[operations[i.operation_id].actor_id],
                    reversed_by.get(i.id),
                )
                for i in items
            ],
            total=total,
            **filters,
        )

    def list_operations(
        self, ctx: AdminContext, community_id: str, bill_id: str, **filters: Any
    ) -> schema.BillOperationPage:
        repo, _ = self._scope(ctx, "property.bill.read")
        if repo.bill(community_id, bill_id) is None:
            raise AppError("resource.not_found")
        items, total = repo.operations(bill_id, **filters)
        names = repo.actor_names([i.actor_id for i in items])
        return schema.BillOperationPage(
            items=[operation_view(i, names[i.actor_id]) for i in items], total=total, **filters
        )

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

    def _replay(
        self, repo: BillingRepository, ctx: AdminContext, key: str, fingerprint: str
    ) -> schema.BillWriteResult | None:
        previous = repo.operation_by_key(key)
        if previous is None:
            return None
        if previous.actor_id != ctx.account_id or previous.request_fingerprint != fingerprint:
            raise AppError("billing.idempotency_conflict")
        return schema.BillWriteResult.model_validate(previous.result)

    def operation_result(self, ctx: AdminContext, key: str) -> schema.BillOperationResult:
        repo, _ = self._scope(ctx, "property.bill.read")
        operation = repo.operation_by_key(key)
        if operation is None or operation.actor_id != ctx.account_id:
            raise AppError("resource.not_found")
        repo, identity, actor, _ = self._protect(
            ctx, PERMISSIONS[cast(Action, operation.action)], None
        )
        result = schema.BillWriteResult.model_validate(operation.result)
        if "property.bill.read" not in identity.effective_permissions(actor.id):
            raise AppError("auth.forbidden")
        if operation.action == "create":
            self._require_creation_permissions(
                identity,
                actor,
                has_basis=result.bill.basis_version_id is not None,
                has_receipt=bool(result.settlement_entries),
            )
        return schema.BillOperationResult(response_status=operation.response_status, result=result)

    @staticmethod
    def _require_creation_permissions(
        identity: AdminIdentity, actor: AdminAccount, *, has_basis: bool, has_receipt: bool
    ) -> None:
        permissions = identity.effective_permissions(actor.id)
        if (has_basis and "property.fee_basis.read" not in permissions) or (
            has_receipt and "property.bill_receipt.create" not in permissions
        ):
            raise AppError("auth.forbidden")

    @staticmethod
    def _entry(
        bill_id: str,
        operation_id: str,
        amount: int,
        received_on: date | None,
        original_id: str | None = None,
    ) -> BillSettlementEntry:
        return BillSettlementEntry(
            id=new_id(),
            bill_id=bill_id,
            operation_id=operation_id,
            entry_type="reversal" if original_id else "receipt",
            source_type="offline",
            amount_cents=amount,
            received_on=received_on,
            reverses_entry_id=original_id,
            created_at=utc_now(),
        )

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
        try:
            repo, identity, actor, community = self._protect(ctx, PERMISSIONS[action], community_id)
            assert community
            if isinstance(data, schema.BillCreate):
                self._require_creation_permissions(
                    identity,
                    actor,
                    has_basis=data.basis_version_id is not None,
                    has_receipt=data.initial_receipt is not None,
                )
            replay = self._replay(repo, ctx, key, fingerprint)
            if replay is not None:
                return replay
            now = utc_now()
            operation_id = new_id()
            entries: list[BillSettlementEntry] = []
            reason: str | None = None
            if action == "create":
                assert isinstance(data, schema.BillCreate)
                house, path = self._house(repo, community, data.house_id, lock=True, exclusive=True)
                replay = self._replay(repo, ctx, key, fingerprint)
                if replay is not None:
                    return replay
                self._require_enabled(community, house, path)
                start = month_date(data.billing_month)
                basis = (
                    repo.basis(house.id, data.basis_version_id) if data.basis_version_id else None
                )
                if data.amount_source == "basis":
                    effective = repo.effective_basis(house.id, start)
                    if effective is None:
                        raise AppError("billing.basis_missing")
                    amount = calculate_amount(
                        effective.area_sqm, effective.unit_price_cents, effective.fixed_amount_cents
                    )
                    if (
                        effective.id != data.basis_version_id
                        or data.expected_calculation_rule_version != RULE_VERSION
                        or data.expected_receivable_cents != amount
                    ):
                        raise AppError("billing.basis_changed")
                else:
                    assert data.receivable_cents is not None
                    amount = data.receivable_cents
                    if data.basis_version_id and (
                        basis is None or basis.effective_from_month > start
                    ):
                        raise AppError("billing.invalid_reference")
                paid = data.initial_receipt.amount_cents if data.initial_receipt else 0
                if paid > amount:
                    raise AppError("billing.overpayment")
                bill = Bill(
                    id=new_id(),
                    property_company_id=repo.company_id,
                    community_id=community_id,
                    house_id=house.id,
                    bill_type="property_fee",
                    period_granularity="month",
                    period_start=start,
                    period_end=next_month(start),
                    external_bill_no=data.external_bill_no,
                    basis_version_id=data.basis_version_id,
                    amount_source=data.amount_source,
                    calculation_rule_version=RULE_VERSION
                    if data.amount_source == "basis"
                    else None,
                    receivable_cents=amount,
                    settled_cents=paid,
                    lifecycle_status="active",
                    due_date=data.due_date,
                    house_label_snapshot=self._label(community, house, path),
                    manual_amount_reason=data.manual_amount_reason,
                    row_version=1,
                    created_by=actor.id,
                    created_at=now,
                    updated_at=now,
                )
                self.db.add(bill)
                if data.initial_receipt:
                    reason = data.initial_receipt.reason
                    entries.append(
                        self._entry(bill.id, operation_id, paid, data.initial_receipt.received_on)
                    )
            else:
                assert bill_id is not None
                existing = repo.bill(community_id, bill_id)
                if existing is None:
                    raise AppError("resource.not_found")
                house, path = self._house(repo, community, existing.house_id, lock=True)
                bill_model = repo.bill(community_id, bill_id, lock=True)
                assert bill_model
                bill = bill_model
                replay = self._replay(repo, ctx, key, fingerprint)
                if replay is not None:
                    return replay
                if bill.lifecycle_status != "active":
                    raise AppError("billing.bill_voided")
                assert isinstance(
                    data,
                    (
                        schema.BillUpdate,
                        schema.BillReasonAction,
                        schema.ReceiptCreate,
                        schema.ReceiptCorrection,
                    ),
                )
                if data.expected_row_version != bill.row_version:
                    raise AppError("billing.version_conflict")
                bill.row_version += 1
                bill.updated_at = now
                if action == "update":
                    assert isinstance(data, schema.BillUpdate)
                    for field in data.model_fields_set - {"expected_row_version"}:
                        setattr(bill, field, getattr(data, field))
                elif action == "void":
                    assert isinstance(data, schema.BillReasonAction)
                    if bill.settled_cents:
                        raise AppError("billing.bill_has_settlement")
                    reason = data.reason
                    bill.lifecycle_status = "voided"
                    bill.void_reason, bill.voided_at, bill.voided_by = reason, now, actor.id
                elif action == "receipt":
                    assert isinstance(data, schema.ReceiptCreate)
                    self._require_enabled(community, house, path)
                    reason = data.reason
                    bill.settled_cents += data.amount_cents
                    entries.append(
                        self._entry(bill.id, operation_id, data.amount_cents, data.received_on)
                    )
                else:
                    assert isinstance(data, (schema.ReceiptCorrection, schema.BillReasonAction))
                    original = repo.entry(bill.id, entry_id or "")
                    if original is None:
                        raise AppError("resource.not_found")
                    if original.entry_type != "receipt":
                        raise AppError("billing.invalid_receipt")
                    if repo.reversals([original.id]):
                        raise AppError("billing.receipt_already_reversed")
                    reason = data.reason
                    bill.settled_cents -= original.amount_cents
                    entries.append(
                        self._entry(
                            bill.id, operation_id, -original.amount_cents, None, original.id
                        )
                    )
                    if action == "correct_receipt":
                        assert isinstance(data, schema.ReceiptCorrection)
                        bill.settled_cents += data.corrected_amount_cents
                        entries.append(
                            self._entry(
                                bill.id,
                                operation_id,
                                data.corrected_amount_cents,
                                data.corrected_received_on,
                            )
                        )
                if not 0 <= bill.settled_cents <= bill.receivable_cents:
                    raise AppError("billing.overpayment")
            self.db.flush()
            self.db.refresh(bill)
            operation = BillOperation(
                id=operation_id,
                property_company_id=repo.company_id,
                bill_id=bill.id,
                bill_version=bill.row_version,
                action=action,
                idempotency_key=key,
                request_fingerprint=fingerprint,
                result={},
                response_status=200 if action in {"update", "void"} else 201,
                reason=reason,
                actor_id=actor.id,
                request_id=request_id,
                created_at=now,
            )
            result = schema.BillWriteResult(
                bill=self._bill_views(repo, community, [bill])[0],
                operation=operation_view(operation, actor.display_name),
                settlement_entries=[entry_view(i, operation, actor.display_name) for i in entries],
            )
            operation.result = result.model_dump(mode="json")
            self.db.add(operation)
            self.db.flush()
            self.db.add_all(entries)
            identity.audit.record(
                actor=actor,
                action="property.bill." + action,
                target_type="bill",
                target_id=bill.id,
                request_id=request_id,
                metadata={
                    "operation_id": operation_id,
                    "bill_version": bill.row_version,
                    "settlement_entry_ids": [i.id for i in entries],
                    "changed_fields": sorted(data.model_fields_set - {"expected_row_version"}),
                },
            )
            self.db.commit()
            return result
        except IntegrityError as exc:
            self.db.rollback()
            if is_unique_violation(exc, "uq_bill_operation_key"):
                repo, identity, actor, _ = self._protect(ctx, PERMISSIONS[action], community_id)
                if isinstance(data, schema.BillCreate):
                    self._require_creation_permissions(
                        identity,
                        actor,
                        has_basis=data.basis_version_id is not None,
                        has_receipt=data.initial_receipt is not None,
                    )
                replay = self._replay(repo, ctx, key, fingerprint)
                if replay is not None:
                    return replay
            for constraint, code in [
                ("uq_bills_active_house_month", "billing.bill_exists"),
                ("uq_bill_entry_reversed", "billing.receipt_already_reversed"),
            ]:
                if is_unique_violation(exc, constraint):
                    raise AppError(code) from exc
            raise
        except Exception:
            self.db.rollback()
            raise
