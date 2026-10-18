from collections.abc import Callable
from datetime import datetime, timedelta

from sqlalchemy.orm import Session, sessionmaker

from backend_app.core.identifiers import new_id
from backend_app.domain.payments.funds import FundsBlocked, retry_seconds
from backend_app.integrations.wechatpay.profit_sharing import ProfitSharing, SharingFact
from backend_app.models.admin import utc_now
from backend_app.models.payments import PaymentChannelRequest, PaymentUnfreezeOrder
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

NO_REMAINING = {"NO_UNSPLIT_AMOUNT", "NO_REMAINING_AMOUNT"}


class UnfreezingService:
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
                    lambda: self.channel.unfreeze(
                        merchant_no=context.merchant_no,
                        channel_transaction_no=context.channel_transaction_no,
                        order_no=context.order_no,
                    )
                )
                if operation == "unfreeze_submit"
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
            if error.outcome == "verified_response" and (
                error.code in NO_REMAINING
                or (operation == "unfreeze_query" and error.code in NOT_FOUND)
            ):
                self._check_remaining(lease, context)
            else:
                self._error(lease, context, operation, error)
            return
        try:
            self.apply(lease, recorded.request_record_id, recorded.response.value)
        except FundsBlocked as error:
            self._pause(lease, context, error.code)

    def _prepare(self, lease: TaskLease) -> tuple[FundsContext, str] | None:
        with self.factory() as db:
            order = db.get(PaymentUnfreezeOrder, lease.target_id)
            assert order is not None
            payment = FundsRepository(db).lock_payment(order.payment_order_id)
            db.refresh(order)
            require_current_lease(db, lease, now=self.clock())
            if order.status in {"succeeded", "no_remaining", "failed"}:
                complete_task(db, lease, now=self.clock())
                db.commit()
                return None
            context = execution_context(db, payment, order)
            previous = latest_request(db, order.id, unfreeze=True)
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
            resubmit = (
                previous is not None
                and previous.operation == "unfreeze_query"
                and previous.outcome == "verified_response"
                and previous.error_code in NOT_FOUND
            )
            operation = (
                "unfreeze_submit"
                if order.status == "pending" and (previous is None or resubmit)
                else "unfreeze_query"
            )
            db.commit()
            return context, operation

    def apply(self, lease: TaskLease, source_id: str, fact: SharingFact) -> None:
        with self.factory() as db:
            order = db.get(PaymentUnfreezeOrder, lease.target_id)
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
        order: PaymentUnfreezeOrder,
        source_id: str,
        fact: SharingFact,
    ) -> None:
        now = self.clock()
        verify_source(db, source_id, context, fact, unfreeze=True)
        verify_receiver_time(fact, now=now)
        if len(fact.receivers) != 1 or order.channel_order_no not in {None, fact.channel_order_no}:
            raise FundsBlocked("FUNDS_FACT_MISMATCH")
        receiver = fact.receivers[0]
        payment = FundsRepository(db).lock_payment(context.payment_id)
        if (
            receiver.receiver_type != "merchant"
            or receiver.receiver_account != context.merchant_no
            or not 0 <= receiver.amount_cents <= payment.amount_cents
        ):
            raise FundsBlocked("FUNDS_FACT_MISMATCH")
        if order.status in {"succeeded", "no_remaining", "failed"}:
            complete_task(db, lease, now=now)
            return
        source = db.get(PaymentChannelRequest, source_id)
        assert source is not None
        order.channel_order_no = fact.channel_order_no
        # Submission acceptance alone never confirms that the original merchant received funds.
        terminal = source.operation == "unfreeze_query" and fact.channel_status == "FINISHED"
        if terminal:
            order.status = "succeeded" if receiver.channel_status == "SUCCESS" else "failed"
            order.unfrozen_cents = receiver.amount_cents if order.status == "succeeded" else None
            order.channel_detail_no = receiver.channel_detail_no
            order.fail_reason = receiver.error_code
            order.finished_at = receiver.finished_at
        else:
            order.status = "processing"
            ensure_task(
                db,
                "unfreeze_query",
                order.id,
                now=now,
                next_run_at=now + timedelta(seconds=retry_seconds(lease.attempt_count)),
                reactivate=True,
            )
        order.updated_at = now
        if lease.task_type == "unfreeze_query" and not terminal:
            reschedule_task(
                db,
                lease,
                now=now,
                next_run_at=now + timedelta(seconds=retry_seconds(lease.attempt_count)),
            )
        else:
            complete_task(db, lease, now=now)

    def _check_remaining(self, lease: TaskLease, context: FundsContext) -> None:
        try:
            recorded = perform_channel_call(
                self.factory,
                operation="remaining_amount",
                target_id=context.payment_id,
                request_snapshot={"channel_transaction_no": context.channel_transaction_no},
                diagnostic_request_id=new_id(),
                lease=lease,
                clock=self.clock,
                call=lambda: self.channel.remaining_amount(
                    channel_transaction_no=context.channel_transaction_no
                ),
                snapshot=lambda value: value,
            )
        except RecordedChannelError as error:
            self._error(lease, context, "remaining_amount", error)
            return
        with self.factory() as db:
            FundsRepository(db).lock_payment(context.payment_id)
            order = db.get(PaymentUnfreezeOrder, context.execution_id)
            assert order is not None
            require_current_lease(db, lease, now=self.clock())
            now = self.clock()
            source = db.get(PaymentChannelRequest, recorded.request_record_id)
            value = recorded.response.value
            if (
                source is None
                or source.operation != "remaining_amount"
                or source.payment_order_id != context.payment_id
                or source.outcome != "verified_response"
                or source.response_snapshot != value
                or source.finished_at is None
                or value.get("channel_transaction_no") != context.channel_transaction_no
                or type(value.get("remaining_cents")) is not int
                or value["remaining_cents"] < 0
            ):
                pause_task(db, lease, now=now, error_code="FUNDS_FACT_MISMATCH")
            elif order.status in {"succeeded", "no_remaining", "failed"}:
                complete_task(db, lease, now=now)
            elif value["remaining_cents"] == 0:
                order.status = "no_remaining"
                order.finished_at = now
                order.updated_at = now
                complete_task(db, lease, now=now)
            elif order.channel_order_no is not None:
                pause_task(db, lease, now=now, error_code="FUNDS_RESULT_CONFLICT")
            else:
                order.status = "pending"
                order.updated_at = now
                due = now + timedelta(seconds=retry_seconds(lease.attempt_count))
                if lease.task_type == "unfreeze_submit":
                    reschedule_task(db, lease, now=now, next_run_at=due)
                else:
                    ensure_task(
                        db, "unfreeze_submit", order.id, now=now, next_run_at=due, reactivate=True
                    )
                    complete_task(db, lease, now=now)
            db.commit()

    def _error(
        self, lease: TaskLease, context: FundsContext, operation: str, error: RecordedChannelError
    ) -> None:
        with self.factory() as db:
            FundsRepository(db).lock_payment(context.payment_id)
            order = db.get(PaymentUnfreezeOrder, context.execution_id)
            assert order is not None
            require_current_lease(db, lease, now=self.clock())
            now = self.clock()
            if order.status in {"succeeded", "no_remaining", "failed"}:
                complete_task(db, lease, now=now)
            elif (
                operation == "unfreeze_submit"
                and error.outcome == "verified_response"
                and error.code in REJECTED
                and order.channel_order_no is None
            ):
                order.status = "failed"
                order.fail_reason = error.code
                order.finished_at = now
                order.updated_at = now
                pause_task(db, lease, now=now, error_code=error.code)
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
