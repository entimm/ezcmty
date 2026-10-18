from collections.abc import Callable
from datetime import datetime, timedelta

from sqlalchemy.orm import Session, sessionmaker

from backend_app.core.identifiers import new_id
from backend_app.domain.payments.funds import FundsBlocked, retry_seconds
from backend_app.integrations.wechatpay.profit_sharing import ProfitSharing, SharingFact
from backend_app.models.admin import utc_now
from backend_app.models.payments import ProfitSharingOrder
from backend_app.repositories.payments.funds import FundsRepository
from backend_app.repositories.payments.tasks import (
    TaskLease,
    complete_task,
    ensure_task,
    pause_task,
    require_current_lease,
    reschedule_task,
)
from backend_app.services.worker.payments.execution import (
    RecordedChannelError,
    perform_channel_call,
)
from backend_app.services.worker.payments.funds_support import (
    CONFIGURATION_ERRORS,
    NOT_FOUND,
    REJECTED,
    FundsContext,
    execution_context,
    latest_request,
    verify_receiver_time,
    verify_source,
)


class ProfitSharingService:
    """Fulfil frozen obligations; never calculate new obligations or release payment occupancy."""

    def __init__(
        self,
        factory: sessionmaker[Session],
        channel: ProfitSharing,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.factory = factory
        self.channel = channel
        self.clock = clock

    def handle(self, lease: TaskLease) -> None:
        prepared = self._prepare(lease)
        if prepared is None:
            return
        context, operation = prepared
        try:
            recorded = perform_channel_call(
                self.factory,
                operation=operation,
                target_id=context.execution_id,
                request_snapshot=context.snapshot(),
                diagnostic_request_id=new_id(),
                lease=lease,
                clock=self.clock,
                call=(
                    lambda: self.channel.create_order(
                        merchant_no=context.merchant_no,
                        channel_transaction_no=context.channel_transaction_no,
                        order_no=context.order_no,
                        receivers=context.receivers,
                    )
                )
                if operation == "profit_sharing_submit"
                else (
                    lambda: self.channel.query_order(
                        merchant_no=context.merchant_no,
                        channel_transaction_no=context.channel_transaction_no,
                        order_no=context.order_no,
                    )
                ),
                snapshot=lambda fact: fact.snapshot(),
            )
        except RecordedChannelError as error:
            self._error(lease, context, operation, error)
            return
        try:
            self.apply(lease, recorded.request_record_id, recorded.response.value)
        except FundsBlocked as error:
            self._pause(lease, context, error.code)

    def _prepare(self, lease: TaskLease) -> tuple[FundsContext, str] | None:
        with self.factory() as db:
            order = db.get(ProfitSharingOrder, lease.target_id)
            assert order is not None
            repository = FundsRepository(db)
            payment = repository.lock_payment(order.payment_order_id)
            db.refresh(order)
            require_current_lease(db, lease, now=self.clock())
            if order.status in {"finished", "rejected"}:
                complete_task(db, lease, now=self.clock())
                db.commit()
                return None
            context = execution_context(db, payment, order)
            previous = latest_request(db, order.id)
            # Reapply independently committed evidence after a crash before making another call.
            if (
                order.status in {"pending", "unknown"}
                and previous is not None
                and previous.outcome == "verified_response"
                and previous.response_snapshot
                and previous.finished_at is not None
            ):
                try:
                    fact = SharingFact.from_snapshot(previous.response_snapshot)
                    self._apply(db, lease, context, order, previous.id, fact)
                except FundsBlocked as error:
                    pause_task(db, lease, now=self.clock(), error_code=error.code)
                db.commit()
                return None
            # Any earlier send may have been accepted. Query the same original number first.
            resubmit = (
                previous is not None
                and previous.operation == "profit_sharing_query"
                and previous.outcome == "verified_response"
                and previous.error_code in NOT_FOUND
            )
            operation = (
                "profit_sharing_submit"
                if order.status == "pending" and (previous is None or resubmit)
                else "profit_sharing_query"
            )
            db.commit()
            return context, operation

    def apply(self, lease: TaskLease, source_id: str, fact: SharingFact) -> None:
        with self.factory() as db:
            order = db.get(ProfitSharingOrder, lease.target_id)
            assert order is not None
            payment = FundsRepository(db).lock_payment(order.payment_order_id)
            db.refresh(order)
            require_current_lease(db, lease, now=self.clock())
            self._apply(db, lease, execution_context(db, payment, order), order, source_id, fact)
            db.commit()

    def _apply(
        self,
        db: Session,
        lease: TaskLease,
        context: FundsContext,
        order: ProfitSharingOrder,
        source_id: str,
        fact: SharingFact,
    ) -> None:
        now = self.clock()
        verify_source(db, source_id, context, fact, unfreeze=False)
        verify_receiver_time(fact, now=now)
        expected = {
            (r.receiver_type, r.receiver_account): r.amount_cents for r in context.receivers
        }
        actual = {(r.receiver_type, r.receiver_account): r.amount_cents for r in fact.receivers}
        if (
            expected != actual
            or len(actual) != len(fact.receivers)
            or order.channel_order_no not in {None, fact.channel_order_no}
        ):
            raise FundsBlocked("FUNDS_FACT_MISMATCH")
        if order.status in {"finished", "rejected"}:
            complete_task(db, lease, now=now)
            return
        repository = FundsRepository(db)
        receiver_facts = {(r.receiver_type, r.receiver_account): r for r in fact.receivers}
        allocations = {a.id: a for a in repository.allocations(context.payment_id)}
        rules = {
            r.id: r
            for r in repository.rule_items(
                repository.lock_payment(context.payment_id).rule_version_id
            )
        }
        for item in repository.sharing_items(order.id):
            rule = rules[allocations[item.allocation_id].rule_version_item_id]
            result = receiver_facts[(rule.receiver_type, rule.receiver_account)]
            if item.result is not None:
                if (
                    result.channel_status == "PENDING"
                    or item.result
                    != ("success" if result.channel_status == "SUCCESS" else "failed")
                    or item.channel_detail_no != result.channel_detail_no
                    or item.finished_at != result.finished_at
                ):
                    raise FundsBlocked("FUNDS_RESULT_CONFLICT")
                continue
            if result.channel_status != "PENDING":
                item.result = "success" if result.channel_status == "SUCCESS" else "failed"
                item.channel_detail_no = result.channel_detail_no
                item.fail_reason = result.error_code
                item.finished_at = result.finished_at
                item.updated_at = now
        order.channel_order_no = fact.channel_order_no
        order.status = "finished" if fact.channel_status == "FINISHED" else "processing"
        order.updated_at = now
        db.flush()
        if order.status == "finished":
            payment = repository.lock_payment(context.payment_id)
            if not repository.remaining(payment.id):
                repository.create_unfreeze(payment, now=now)
            else:
                try:
                    repository.create_sharing(
                        payment,
                        now=now,
                        next_run_at=now
                        + timedelta(
                            seconds=retry_seconds(len(repository.sharing_orders(payment.id)))
                        ),
                    )
                except FundsBlocked as error:
                    pause_task(db, lease, now=now, error_code=error.code)
                    return
        else:
            ensure_task(
                db,
                "profit_sharing_query",
                order.id,
                now=now,
                next_run_at=now + timedelta(seconds=retry_seconds(lease.attempt_count)),
                reactivate=True,
            )
        if lease.task_type == "profit_sharing_query" and order.status != "finished":
            reschedule_task(
                db,
                lease,
                now=now,
                next_run_at=now + timedelta(seconds=retry_seconds(lease.attempt_count)),
            )
        else:
            complete_task(db, lease, now=now)

    def _error(
        self, lease: TaskLease, context: FundsContext, operation: str, error: RecordedChannelError
    ) -> None:
        with self.factory() as db:
            FundsRepository(db).lock_payment(context.payment_id)
            order = db.get(ProfitSharingOrder, context.execution_id)
            assert order is not None
            require_current_lease(db, lease, now=self.clock())
            now = self.clock()
            if order.status in {"finished", "rejected"}:
                complete_task(db, lease, now=now)
            elif (
                operation == "profit_sharing_submit"
                and error.outcome == "verified_response"
                and error.code in REJECTED
                and order.channel_order_no is None
            ):
                order.status = "rejected"
                order.updated_at = now
                pause_task(db, lease, now=now, error_code=error.code)
            elif (
                operation == "profit_sharing_query"
                and error.outcome == "verified_response"
                and error.code in NOT_FOUND
            ):
                if order.channel_order_no is not None:
                    pause_task(db, lease, now=now, error_code="FUNDS_RESULT_CONFLICT")
                else:
                    order.status = "pending"
                    order.updated_at = now
                    due = now + timedelta(seconds=retry_seconds(lease.attempt_count))
                    if lease.task_type == "profit_sharing_submit":
                        reschedule_task(db, lease, now=now, next_run_at=due)
                    else:
                        ensure_task(
                            db,
                            "profit_sharing_submit",
                            order.id,
                            now=now,
                            next_run_at=due,
                            reactivate=True,
                        )
                        complete_task(db, lease, now=now)
            else:
                order.status = "processing" if order.channel_order_no else "unknown"
                order.updated_at = now
                if error.code in CONFIGURATION_ERRORS:
                    pause_task(db, lease, now=now, error_code=error.code)
                else:
                    reschedule_task(
                        db,
                        lease,
                        now=now,
                        next_run_at=now
                        + timedelta(
                            seconds=retry_seconds(lease.attempt_count, error.retry_after_seconds)
                        ),
                        error_code=error.code,
                    )
            db.commit()

    def _pause(self, lease: TaskLease, context: FundsContext, code: str) -> None:
        with self.factory() as db:
            FundsRepository(db).lock_payment(context.payment_id)
            require_current_lease(db, lease, now=self.clock())
            pause_task(db, lease, now=self.clock(), error_code=code)
            db.commit()
