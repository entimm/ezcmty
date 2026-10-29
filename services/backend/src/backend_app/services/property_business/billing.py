from datetime import date
from typing import Any, cast

from sqlalchemy.orm import Session

from backend_app.core.errors import AppError
from backend_app.core.identifiers import new_id
from backend_app.domain.billing import (
    RULE_VERSION,
    Action,
    business_today,
    calculate_amount,
    month_date,
    next_month,
)
from backend_app.domain.billing.basis import FeeBasisCreationCommand
from backend_app.domain.billing.creation import BillCreationCommand, creation_actions
from backend_app.domain.billing.posting import append_receipt
from backend_app.models.admin import utc_now
from backend_app.models.billing import Bill, BillOperation, BillSettlementEntry
from backend_app.models.housing import House, SpaceNode
from backend_app.models.property import Community
from backend_app.repositories.billing import BillingRepository
from backend_app.schemas import billing as schema
from backend_app.schemas.mappers.billing import (
    basis_view,
    bill_view,
    entry_view,
    historical_write_result,
    operation_view,
)
from backend_app.services.property_business.bill_creation import create_bill
from backend_app.services.property_business.commands import (
    BillMutation,
    BillReasonAction,
    BillUpdate,
    ReceiptCorrection,
    ReceiptCreate,
    require_fields,
)
from backend_app.services.property_business.context import BusinessActor, PropertyBusinessContext
from backend_app.services.property_business.fee_basis_creation import create_fee_basis

PERMISSIONS: dict[Action, str] = {
    "create": "bill.manage",
    "update": "bill.manage",
    "receipt": "bill_receipt.create",
    "correct_receipt": "bill_receipt.correct",
    "reverse_receipt": "bill_receipt.correct",
    "void": "bill.void",
}


class BillingUseCases:
    def __init__(self, db: Session):
        self.db = db

    def _scope(
        self, ctx: PropertyBusinessContext, permission: str
    ) -> tuple[BillingRepository, PropertyBusinessContext]:
        ctx.require(permission)
        return (BillingRepository(self.db, ctx.company_id), ctx)

    def _protect(
        self, ctx: PropertyBusinessContext, permission: str, community_id: str | None
    ) -> tuple[BillingRepository, PropertyBusinessContext, BusinessActor, Community | None]:
        actor = ctx.require(permission, lock=True, shared=True)
        repo = BillingRepository(self.db, ctx.company_id)
        community = repo.community(community_id, lock=True) if community_id else None
        if community_id is not None and community is None:
            raise AppError("resource.not_found")
        return (repo, ctx, actor, community)

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
        return (house, path)

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
        self, ctx: PropertyBusinessContext, community_id: str, house_id: str, **filters: Any
    ) -> schema.FeeBasisPage:
        repo, _ = self._scope(ctx, "bill.read")
        self._house(repo, self._community(repo, community_id), house_id)
        items, total = repo.bases(house_id, **filters)
        return schema.FeeBasisPage(items=[basis_view(i) for i in items], total=total, **filters)

    def get_basis(
        self, ctx: PropertyBusinessContext, community_id: str, house_id: str, version_id: str
    ) -> schema.FeeBasisVersion:
        repo, _ = self._scope(ctx, "bill.read")
        self._house(repo, self._community(repo, community_id), house_id)
        item = repo.basis(house_id, version_id)
        if item is None:
            raise AppError("resource.not_found")
        return basis_view(item)

    def create_basis(
        self,
        ctx: PropertyBusinessContext,
        community_id: str,
        house_id: str,
        data: FeeBasisCreationCommand,
        request_id: str,
        expected_latest_version_no: int,
    ) -> schema.FeeBasisVersion:
        if data.house_id != house_id:
            raise AppError("VALIDATION_ERROR")
        self._protect(ctx, "fee_basis.manage", community_id)
        result = create_fee_basis(
            self.db,
            company_id=ctx.company_id,
            community_id=community_id,
            actor_id=ctx.actor_id,
            context=ctx,
            command=data,
            expected_latest_version_no=expected_latest_version_no,
            request_id=request_id,
        )
        return basis_view(result.basis)

    def calculate(
        self, ctx: PropertyBusinessContext, community_id: str, house_id: str, billing_month: str
    ) -> schema.FeeCalculation:
        repo, _ = self._scope(ctx, "bill.read")
        community = self._community(repo, community_id)
        house, path = self._house(repo, community, house_id)
        start = month_date(billing_month)
        basis = repo.effective_basis(house_id, start)
        return schema.FeeCalculation(
            available=basis is not None,
            billing_month=billing_month,
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
        reserved = repo.reserved_bill_ids([i.id for i in items])
        return [
            bill_view(
                i,
                bases.get(i.basis_version_id or ""),
                states.get(i.house_id, False),
                today,
                payment_in_progress=i.id in reserved,
            )
            for i in items
        ]

    def list_bills(
        self, ctx: PropertyBusinessContext, community_id: str, **filters: Any
    ) -> schema.BillPage:
        repo, _ = self._scope(ctx, "bill.read")
        community = self._community(repo, community_id)
        today = business_today()
        items, total = repo.bill_list(community_id, today=today, **filters)
        return schema.BillPage(
            items=self._bill_views(repo, community, items, today=today),
            total=total,
            page=filters["page"],
            page_size=filters["page_size"],
        )

    def get_bill(
        self, ctx: PropertyBusinessContext, community_id: str, bill_id: str
    ) -> schema.Bill:
        repo, _ = self._scope(ctx, "bill.read")
        community = self._community(repo, community_id)
        item = repo.bill(community_id, bill_id)
        if item is None:
            raise AppError("resource.not_found")
        return self._bill_views(repo, community, [item])[0]

    def list_entries(
        self, ctx: PropertyBusinessContext, community_id: str, bill_id: str, **filters: Any
    ) -> schema.SettlementEntryPage:
        repo, _ = self._scope(ctx, "bill.read")
        if repo.bill(community_id, bill_id) is None:
            raise AppError("resource.not_found")
        items, total = repo.entries(bill_id, **filters)
        operations = repo.operation_map([i.operation_id for i in items])
        names = repo.actor_names([i.actor_id for i in operations.values() if i.actor_id])
        reversed_by = repo.reversals([i.id for i in items])
        return schema.SettlementEntryPage(
            items=[
                entry_view(
                    i,
                    operations[i.operation_id],
                    names.get(operations[i.operation_id].actor_id or "", "系统"),
                    reversed_by.get(i.id),
                )
                for i in items
            ],
            total=total,
            **filters,
        )

    def list_operations(
        self, ctx: PropertyBusinessContext, community_id: str, bill_id: str, **filters: Any
    ) -> schema.BillOperationPage:
        repo, _ = self._scope(ctx, "bill.read")
        if repo.bill(community_id, bill_id) is None:
            raise AppError("resource.not_found")
        items, total = repo.operations(bill_id, **filters)
        names = repo.actor_names([i.actor_id for i in items if i.actor_id])
        return schema.BillOperationPage(
            items=[operation_view(i, names.get(i.actor_id or "", "系统")) for i in items],
            total=total,
            **filters,
        )

    def _replay(
        self, repo: BillingRepository, ctx: PropertyBusinessContext, key: str, fingerprint: str
    ) -> schema.BillWriteResult | None:
        previous = repo.operation_by_key(key)
        if previous is None:
            return None
        if previous.actor_id != ctx.actor_id or previous.request_fingerprint != fingerprint:
            raise AppError("billing.idempotency_conflict")
        return historical_write_result(previous.result)

    def operation_result(
        self, ctx: PropertyBusinessContext, key: str
    ) -> schema.BillOperationResult:
        repo, _ = self._scope(ctx, "bill.read")
        operation = repo.operation_by_key(key)
        if operation is None or operation.actor_id != ctx.actor_id:
            raise AppError("resource.not_found")
        repo, identity, actor, _ = self._protect(
            ctx, PERMISSIONS[cast(Action, operation.action)], None
        )
        result = historical_write_result(operation.result)
        if "bill.read" not in actor.permissions:
            raise AppError("auth.forbidden")
        if operation.action == "create":
            self._require_creation_actions(
                identity,
                actor,
                has_basis=result.bill.basis_version_id is not None,
                has_receipt=bool(result.settlement_entries),
            )
        assert operation.response_status is not None
        return schema.BillOperationResult(response_status=operation.response_status, result=result)

    @staticmethod
    def _require_creation_actions(
        identity: PropertyBusinessContext,
        actor: BusinessActor,
        *,
        has_basis: bool,
        has_receipt: bool,
    ) -> None:
        identity.require(
            *creation_actions(
                initial_paid_cents=1 if has_receipt else 0,
                basis_version_id="reference" if has_basis else None,
            ),
            lock=True,
            shared=True,
        )

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
            payment_order_item_id=None,
            amount_cents=amount,
            received_on=received_on,
            reverses_entry_id=original_id,
            created_at=utc_now(),
        )

    def write(
        self,
        ctx: PropertyBusinessContext,
        community_id: str,
        action: Action,
        data: BillMutation,
        key: str,
        request_id: str,
        fingerprint: str,
        *,
        bill_id: str | None = None,
        entry_id: str | None = None,
    ) -> schema.BillWriteResult:
        expected = {
            "update": BillUpdate,
            "receipt": ReceiptCreate,
            "correct_receipt": ReceiptCorrection,
            "reverse_receipt": BillReasonAction,
            "void": BillReasonAction,
        }
        if action not in expected or not isinstance(data, expected[action]):
            raise AppError("VALIDATION_ERROR")
        repo, identity, actor, community = self._protect(ctx, PERMISSIONS[action], community_id)
        assert community
        replay = self._replay(repo, ctx, key, fingerprint)
        if replay is not None:
            return replay
        now = utc_now()
        operation_id = new_id()
        entries: list[BillSettlementEntry] = []
        reason: str | None = None
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
        if action != "update" and repo.reservation(bill.id) is not None:
            raise AppError("payment.bill_reserved")
        if bill.lifecycle_status != "active":
            raise AppError("billing.bill_voided")
        assert isinstance(data, (BillUpdate, BillReasonAction, ReceiptCreate, ReceiptCorrection))
        if data.expected_row_version != bill.row_version:
            raise AppError("billing.version_conflict")
        bill.row_version += 1
        bill.updated_at = now
        if action == "update":
            assert isinstance(data, BillUpdate)
            require_fields(data.changes, frozenset({"external_bill_no", "due_date"}))
            for field, value in data.changes.values.items():
                setattr(bill, field, value)
        elif action == "void":
            assert isinstance(data, BillReasonAction)
            if bill.settled_cents:
                raise AppError("billing.bill_has_settlement")
            reason = data.reason
            bill.lifecycle_status = "voided"
            bill.void_reason, bill.voided_at, bill.voided_by = (reason, now, actor.id)
        elif action == "receipt":
            assert isinstance(data, ReceiptCreate)
            self._require_enabled(community, house, path)
            reason = data.reason
            if bill.settled_cents + data.amount_cents > bill.receivable_cents:
                raise AppError("billing.overpayment")
            entries.append(append_receipt(bill, operation_id, data.amount_cents, data.received_on))
        else:
            assert isinstance(data, (ReceiptCorrection, BillReasonAction))
            original = repo.entry(bill.id, entry_id or "")
            if original is None:
                raise AppError("resource.not_found")
            if original.entry_type != "receipt" or original.source_type != "offline":
                raise AppError("billing.invalid_receipt")
            if repo.reversals([original.id]):
                raise AppError("billing.receipt_already_reversed")
            reason = data.reason
            bill.settled_cents -= original.amount_cents
            entries.append(
                self._entry(bill.id, operation_id, -original.amount_cents, None, original.id)
            )
            if action == "correct_receipt":
                assert isinstance(data, ReceiptCorrection)
                if bill.settled_cents + data.corrected_amount_cents > bill.receivable_cents:
                    raise AppError("billing.overpayment")
                entries.append(
                    append_receipt(
                        bill, operation_id, data.corrected_amount_cents, data.corrected_received_on
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
            actor_type="admin",
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
        identity.record(
            actor=actor,
            action="property.bill." + action,
            target_type="bill",
            target_id=bill.id,
            request_id=request_id,
            metadata={
                "operation_id": operation_id,
                "bill_version": bill.row_version,
                "settlement_entry_ids": [i.id for i in entries],
                "changed_fields": sorted(data.input_fields - {"expected_row_version"}),
            },
        )
        return result

    def create(
        self,
        ctx: PropertyBusinessContext,
        community_id: str,
        data: BillCreationCommand,
        key: str,
        fingerprint: str,
        request_id: str,
        input_fields: frozenset[str],
    ) -> schema.BillWriteResult:
        self._protect(ctx, "bill.manage", community_id)
        result = create_bill(
            self.db,
            company_id=ctx.company_id or "",
            community_id=community_id,
            actor_id=ctx.actor_id,
            context=ctx,
            command=data,
            key=key,
            fingerprint=fingerprint,
            request_id=request_id,
            input_fields=input_fields,
        )
        return historical_write_result(result.result)

    def recover_conflict(
        self,
        ctx: PropertyBusinessContext,
        community_id: str,
        action: Action,
        key: str,
        fingerprint: str,
        creation: BillCreationCommand | None,
    ) -> schema.BillWriteResult | None:
        repo, identity, actor, _ = self._protect(ctx, PERMISSIONS[action], community_id)
        if creation is not None:
            self._require_creation_actions(
                identity,
                actor,
                has_basis=creation.basis_version_id is not None,
                has_receipt=creation.initial_receipt is not None,
            )
        return self._replay(repo, ctx, key, fingerprint)
