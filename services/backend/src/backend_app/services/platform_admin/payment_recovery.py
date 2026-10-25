"""Administrative recovery schedules existing work; it never asserts a funds result."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend_app.core.errors import AppError
from backend_app.domain.admin.identity import AdminIdentity
from backend_app.domain.payments.configuration import fingerprint
from backend_app.domain.payments.funds import FundsBlocked
from backend_app.models.admin import AdminAccount, utc_now
from backend_app.models.payments import (
    PaymentOrder,
    PaymentReconciliationDiscrepancy,
    PaymentReconciliationRun,
    PaymentTask,
)
from backend_app.repositories.admin import AdminRepository
from backend_app.repositories.billing import BillingRepository
from backend_app.repositories.payments.funds import INFLIGHT, FundsRepository
from backend_app.repositories.payments.management import PaymentManagementRepository
from backend_app.repositories.payments.orders import OrdersRepository
from backend_app.repositories.payments.reconciliation import lock_run, schedule_reconciliation
from backend_app.repositories.payments.tasks import ensure_task
from backend_app.schemas.mappers import payment_management as mapper
from backend_app.schemas.payments import management as schema
from backend_app.services.contracts.admin import AdminContext


class PaymentRecoveryService:
    def __init__(self, db: Session):
        self.db = db
        self.identity = AdminIdentity(AdminRepository(db, "platform_admin"))
        self.repo = PaymentManagementRepository(db)

    def _precheck(self, ctx: AdminContext, *permissions: str) -> None:
        self.identity.require_full_session(ctx)
        actor = self.identity.session_account(ctx.account_id, ctx.version)
        if actor.must_change_password:
            raise AppError("auth.password_change_required")
        if not set(permissions) <= set(self.identity.effective_permissions(actor.id)):
            raise AppError("auth.forbidden")

    def _actor(self, ctx: AdminContext, *permissions: str) -> AdminAccount:
        actor = self.identity.actor(ctx)
        if actor.must_change_password:
            raise AppError("auth.password_change_required")
        if not set(permissions) <= set(self.identity.effective_permissions(actor.id)):
            raise AppError("auth.forbidden")
        return actor

    def _payment(
        self, ctx: AdminContext, payment_id: str, permission: str
    ) -> tuple[PaymentOrder, AdminAccount]:
        original = self.repo.payment(payment_id)
        if original.status == "succeeded":
            actor = self._actor(ctx, permission)
            return FundsRepository(self.db).lock_payment(payment_id), actor
        # The company precedes both administrator and payer; guard_order protects the
        # original house path and bill even when authorization has since been revoked.
        if BillingRepository(self.db, original.property_company_id).protect_company() is None:
            raise AppError("resource.not_found")
        actor = self._actor(ctx, permission)
        payment, _ = OrdersRepository(self.db).guard_order(payment_id)
        return payment, actor

    def _schedule_payment(self, payment: PaymentOrder, *, now: datetime) -> PaymentTask:
        if payment.status == "closed":
            raise AppError("payment.recovery_not_allowed")
        if payment.status == "succeeded":
            try:
                task = FundsRepository(self.db).recover(payment, now=now)
            except FundsBlocked:
                raise AppError("payment.recovery_not_allowed") from None
            if task is None:
                raise AppError("payment.recovery_not_allowed")
            return task
        task_type = (
            "payment_submit"
            if payment.status == "pending"
            else "payment_close"
            if payment.status == "closing"
            else "payment_query"
        )
        return ensure_task(self.db, task_type, payment.id, now=now, reactivate=True)

    def _difference(
        self, original: PaymentReconciliationDiscrepancy
    ) -> tuple[PaymentReconciliationRun, PaymentReconciliationDiscrepancy]:
        run = lock_run(self.db, original.reconciliation_run_id)
        item = self.db.scalars(
            select(PaymentReconciliationDiscrepancy)
            .where(PaymentReconciliationDiscrepancy.id == original.id)
            .with_for_update(of=PaymentReconciliationDiscrepancy)
            .execution_options(populate_existing=True)
        ).one()
        return run, item

    @staticmethod
    def _token(actual: str, expected: str) -> None:
        if actual != expected:
            raise AppError("resource.conflict")

    def _audit(
        self,
        actor: AdminAccount,
        target_type: str,
        target_id: str,
        request_id: str,
        *,
        reason: str,
        company_id: str | None = None,
        **metadata: object,
    ) -> None:
        self.identity.audit.record(
            actor=actor,
            action="payment." + target_type + ".recover",
            target_type=target_type,
            target_id=target_id,
            property_company_id=company_id,
            request_id=request_id,
            metadata={"reason": reason, **metadata},
        )

    def payment(
        self,
        ctx: AdminContext,
        payment_id: str,
        data: schema.PaymentRecoveryRequest,
        request_id: str,
    ) -> schema.PaymentRecoveryAccepted:
        permission = "platform.payment.recover"
        self._precheck(ctx, permission)
        payment, actor = self._payment(ctx, payment_id, permission)
        self._token(mapper.payment_token(self.db, payment), data.expected_state_token)
        now = utc_now()
        task = self._schedule_payment(payment, now=now)
        self._audit(
            actor,
            "payment_order",
            payment.id,
            request_id,
            reason=data.reason,
            company_id=payment.property_company_id,
            task_id=task.id,
        )
        self.db.commit()
        return schema.PaymentRecoveryAccepted(
            target_type="payment_order", target_id=payment_id, accepted_at=now
        )

    def run(
        self,
        ctx: AdminContext,
        run_id: str,
        data: schema.PaymentRecoveryRequest,
        request_id: str,
    ) -> schema.PaymentRecoveryAccepted:
        permission = "platform.payment_reconciliation.manage"
        self._precheck(ctx, permission)
        actor = self._actor(ctx, permission)
        self.repo.run(run_id)
        run = lock_run(self.db, run_id)
        self._token(mapper.run_token(run), data.expected_state_token)
        now = utc_now()
        task = schedule_reconciliation(self.db, run, now=now)
        self._audit(
            actor, "reconciliation_run", run.id, request_id, reason=data.reason, task_id=task.id
        )
        self.db.commit()
        return schema.PaymentRecoveryAccepted(
            target_type="reconciliation_run", target_id=run_id, accepted_at=now
        )

    def discrepancy(
        self,
        ctx: AdminContext,
        discrepancy_id: str,
        data: schema.PaymentRecoveryRequest,
        request_id: str,
    ) -> schema.PaymentRecoveryAccepted:
        permission = "platform.payment.recover"
        self._precheck(ctx, permission)
        original = self.repo.discrepancy(discrepancy_id)
        if original.payment_order_id is None:
            raise AppError("payment.recovery_not_allowed")
        original_payment_id = original.payment_order_id
        payment, actor = self._payment(ctx, original_payment_id, permission)
        run, item = self._difference(original)
        self._token(mapper.discrepancy_token(run, item), data.expected_state_token)
        if item.status == "resolved":
            raise AppError("resource.conflict")
        if item.payment_order_id != original_payment_id:
            raise AppError("resource.conflict")
        now = utc_now()
        task = self._schedule_payment(payment, now=now)
        schedule_reconciliation(self.db, run, now=now)
        item.status, item.updated_at = "observing", now
        self._audit(
            actor,
            "reconciliation_discrepancy",
            item.id,
            request_id,
            reason=data.reason,
            company_id=payment.property_company_id,
            task_id=task.id,
            evidence=mapper.canonical(item.evidence),
        )
        self.db.commit()
        return schema.PaymentRecoveryAccepted(
            target_type="reconciliation_discrepancy", target_id=discrepancy_id, accepted_at=now
        )

    def _normally_recoverable(self, item: PaymentReconciliationDiscrepancy) -> bool:
        if item.payment_order_id is None:
            return False
        payment = self.repo.payment(item.payment_order_id)
        check = item.evidence.get("check_code")
        if check in {"payment_status", "payment_amount", "bill_posting"}:
            return payment.status not in {"succeeded", "closed"}
        if payment.status != "succeeded":
            return False
        funds = FundsRepository(self.db)
        unfreezes = funds.unfreeze_orders(payment.id)
        if check in {"unfreeze_status", "unfreeze_amount"}:
            if unfreezes:
                return unfreezes[-1].status not in {"succeeded", "no_remaining"}
            return (
                bool(funds.allocations(payment.id))
                and not funds.remaining(payment.id)
                and not any(order.status in INFLIGHT for order in funds.sharing_orders(payment.id))
            )
        if check in {"profit_sharing_status", "profit_sharing_amount"}:
            if unfreezes:
                return False  # Permanent barrier; external handling cannot erase the obligation.
            orders = funds.sharing_orders(payment.id)
            if any(order.status in INFLIGHT for order in orders):
                return True
            accepted = sum(o.channel_order_no is not None or o.status == "finished" for o in orders)
            return bool(funds.remaining(payment.id)) and accepted < 50
        return False

    def external_resolution(
        self,
        ctx: AdminContext,
        discrepancy_id: str,
        data: schema.ReconciliationExternalResolutionRequest,
        request_id: str,
    ) -> schema.ManagedReconciliationDiscrepancy:
        permissions = ("platform.payment_reconciliation.read", "platform.payment.recover")
        self._precheck(ctx, *permissions)
        actor = self._actor(ctx, *permissions)
        run, item = self._difference(self.repo.discrepancy(discrepancy_id))
        self._token(mapper.discrepancy_token(run, item), data.expected_state_token)
        tasks = self.db.scalars(
            select(PaymentTask)
            .where(PaymentTask.reconciliation_run_id == run.id)
            .order_by(PaymentTask.id)
            .with_for_update(of=PaymentTask)
            .execution_options(populate_existing=True)
        ).all()
        if (
            item.status == "resolved"
            or run.status == "running"
            or any(task.status == "running" for task in tasks)
        ):
            raise AppError("resource.conflict")
        if self._normally_recoverable(item):
            raise AppError("payment.recovery_not_allowed")
        before = mapper.canonical(
            {
                "status": item.status,
                "evidence": item.evidence,
                "expected_cents": item.expected_cents,
                "actual_cents": item.actual_cents,
                "resolved_at": item.resolved_at,
                "resolved_by": item.resolved_by,
                "resolution_note": item.resolution_note,
            }
        )
        now = utc_now()
        item.status, item.resolved_at, item.resolved_by = "resolved", now, actor.id
        # Do not copy free-form reasons or credentials into an ordinary discrepancy view.
        # The bounded fingerprint references the complete restricted audit evidence.
        item.resolution_note = "已核实外部处置；依据引用摘要：" + fingerprint(
            data.evidence_reference
        )
        item.updated_at = now
        self.identity.audit.record(
            actor=actor,
            action="payment.reconciliation_discrepancy.external_resolution",
            target_type="reconciliation_discrepancy",
            target_id=item.id,
            request_id=request_id,
            metadata={
                "reason": data.reason,
                "evidence_reference": data.evidence_reference,
                "before": before,
                "after": {"status": "resolved", "resolved_by": actor.id},
                "source_request_id": item.evidence.get("source_request_id"),
                "source_digest": item.evidence.get("source_digest"),
            },
        )
        self.db.flush()
        result = mapper.discrepancy_view(self.db, item)
        self.db.commit()
        return result
