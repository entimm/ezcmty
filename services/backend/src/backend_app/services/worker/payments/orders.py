from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, sessionmaker

from backend_app.core.config import Settings
from backend_app.core.errors import AppError
from backend_app.core.identifiers import new_id
from backend_app.domain.payments.configuration import validate_amount
from backend_app.integrations.wechatpay.client import ChannelResponse, WechatPayError
from backend_app.integrations.wechatpay.evidence import request_snapshot
from backend_app.integrations.wechatpay.payments import PaymentFact, Payments, PrepayResult
from backend_app.integrations.wechatpay.profit_sharing import ProfitSharing
from backend_app.models.admin import utc_now
from backend_app.models.payments import (
    PaymentChannelNotification,
    PaymentChannelRequest,
    PaymentOrder,
    ProfitSharingRuleVersionItem,
)
from backend_app.repositories.payments.channel_records import save_response, start_request
from backend_app.repositories.payments.configuration import ConfigurationRepository
from backend_app.repositories.payments.orders import OrdersRepository
from backend_app.repositories.payments.tasks import (
    TaskLease,
    complete_task,
    ensure_task,
    pause_task,
    require_current_lease,
    reschedule_task,
)
from backend_app.services.worker.payments.confirmation import (
    ConfirmationService,
    PaymentConfirmationError,
)
from backend_app.services.worker.payments.execution import (
    perform_channel_call,
)


@dataclass(frozen=True)
class OrderRequest:
    id: str
    merchant_binding_id: str
    merchant_no: str
    provider_no: str
    order_no: str
    amount_cents: int
    payer_openid: str = field(repr=False)
    expires_at: datetime

    def snapshot(self, operation: str) -> dict[str, Any]:
        return request_snapshot(
            operation,
            {
                "merchant_no": self.merchant_no,
                "service_provider_merchant_no": self.provider_no,
                "order_no": self.order_no,
                "amount_cents": self.amount_cents,
                "payer_openid": self.payer_openid,
                "expires_at": self.expires_at,
            },
        )


class OrderService:
    def __init__(
        self,
        factory: sessionmaker[Session],
        settings: Settings,
        payments: Payments,
        profit_sharing: ProfitSharing,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.factory, self.settings = factory, settings
        self.payments, self.profit_sharing, self.clock = payments, profit_sharing, clock
        self.confirmation = ConfirmationService(
            factory, app_id=settings.wechat_miniapp_app_id, clock=clock
        )

    def handle(self, lease: TaskLease) -> None:
        {"payment_submit": self.submit, "payment_query": self.query, "payment_close": self.close}[
            lease.task_type
        ](lease)

    def _request(self, db: Session, order: PaymentOrder) -> OrderRequest:
        repo = OrdersRepository(db)
        binding = repo.binding(order)
        # Current configuration cannot replace the immutable original payer, merchant or deadline.
        guard = repo.guard_bill(repo.items(order.id)[0][0].bill_id, order.payer_user_id, lock=False)
        return OrderRequest(
            order.id,
            binding.id,
            binding.merchant_no,
            binding.service_provider_merchant_no,
            order.order_no,
            order.amount_cents,
            guard.payer.wechat_openid,
            order.expires_at,
        )

    def _success(self, order_id: str, lease: TaskLease) -> bool:
        with self.factory() as db:
            record = db.scalar(
                select(PaymentChannelRequest)
                .where(
                    PaymentChannelRequest.payment_order_id == order_id,
                    PaymentChannelRequest.operation == "payment_query",
                    PaymentChannelRequest.outcome == "verified_response",
                    PaymentChannelRequest.error_code.is_(None),
                    PaymentChannelRequest.finished_at.is_not(None),
                    PaymentChannelRequest.response_snapshot["channel_status"].as_string()
                    == "SUCCESS",
                )
                .order_by(PaymentChannelRequest.created_at.desc(), PaymentChannelRequest.id.desc())
                .limit(1)
            )
            if record is not None:
                assert record.response_snapshot is not None
                fact, source = PaymentFact.from_snapshot(record.response_snapshot), record.id
                notice_id = None
            else:
                order = db.get(PaymentOrder, order_id)
                if order is None:
                    raise ValueError("Payment task has no order")
                notice = db.scalar(
                    select(PaymentChannelNotification)
                    .where(
                        PaymentChannelNotification.notification_type == "payment_success",
                        PaymentChannelNotification.status.in_(("pending", "processed")),
                        PaymentChannelNotification.payload["order_no"].as_string()
                        == order.order_no,
                    )
                    .order_by(PaymentChannelNotification.created_at, PaymentChannelNotification.id)
                    .limit(1)
                )
                if notice is None:
                    return False
                fact, source = PaymentFact.from_snapshot(notice.payload), None
                notice_id = notice.id
        self.confirmation.confirm(
            order_id, fact, lease=lease, source_request_id=source, notification_id=notice_id
        )
        return True

    def _terminal(self, db: Session, order: PaymentOrder, lease: TaskLease) -> bool:
        if order.status not in {"succeeded", "closed"}:
            return False
        require_current_lease(db, lease, now=self.clock())
        complete_task(db, lease, now=self.clock())
        db.commit()
        return True

    def _closed(self, db: Session, order: PaymentOrder, lease: TaskLease) -> None:
        now = self.clock()
        require_current_lease(db, lease, now=now)
        if OrdersRepository(db).awaiting_posting(order, app_id=self.settings.wechat_miniapp_app_id):
            if lease.task_type == "payment_query":
                reschedule_task(db, lease, now=now, next_run_at=now)
            else:
                ensure_task(db, "payment_query", order.id, now=now, reactivate=True)
                complete_task(db, lease, now=now)
            return
        if order.status not in {"succeeded", "closed"}:
            order.status, order.closed_at, order.updated_at = "closed", now, now
            order.prepay_token = None
            db.flush()
            OrdersRepository(db).release(order.id)
        complete_task(db, lease, now=now)

    def _prevent_sending(self, db: Session, order: PaymentOrder, lease: TaskLease) -> None:
        prior = db.scalar(
            select(PaymentChannelRequest.id)
            .where(
                PaymentChannelRequest.payment_order_id == order.id,
                PaymentChannelRequest.operation == "payment_submit",
            )
            .limit(1)
        )
        if prior is None:
            self._closed(db, order, lease)
        else:
            order.status, order.updated_at = "closing", self.clock()
            ensure_task(db, "payment_close", order.id, now=self.clock(), reactivate=True)
            complete_task(db, lease, now=self.clock())

    def _failed(self, lease: TaskLease, error: WechatPayError) -> None:
        with self.factory() as db:
            repo = OrdersRepository(db)
            order, _ = repo.guard_order(lease.target_id)
            if self._terminal(db, order, lease):
                return
            now = self.clock()
            require_current_lease(db, lease, now=now)
            if order.status != "closing":
                order.status, order.updated_at = "unknown", now
            if lease.task_type == "payment_submit":
                ensure_task(db, "payment_query", order.id, now=now, reactivate=True)
                complete_task(db, lease, now=now)
            else:
                if (
                    lease.task_type == "payment_query"
                    and error.outcome == "verified_response"
                    and error.code in {"ORDER_NOT_EXIST", "ORDER_NOT_EXISTS"}
                    and order.status != "closing"
                    and now < order.expires_at
                ):
                    ensure_task(db, "payment_submit", order.id, now=now, reactivate=True)
                reschedule_task(
                    db,
                    lease,
                    now=now,
                    next_run_at=now
                    + timedelta(
                        seconds=max(
                            error.retry_after_seconds or 0,
                            min(300, 2 ** min(lease.attempt_count, 8)),
                        )
                    ),
                    error_code=error.code,
                )
            db.commit()

    def _quarantine(self, lease: TaskLease, code: str) -> None:
        with self.factory() as db:
            OrdersRepository(db).guard_order(lease.target_id)
            require_current_lease(db, lease, now=self.clock())
            pause_task(db, lease, now=self.clock(), error_code=code)
            db.commit()

    def submit(self, lease: TaskLease) -> None:
        try:
            if self._success(lease.target_id, lease):
                return
            with self.factory() as db:
                repo = OrdersRepository(db)
                order, authorized = repo.guard_order(lease.target_id)
                if self._terminal(db, order, lease):
                    return
                require_current_lease(db, lease, now=self.clock())
                prior = db.scalar(
                    select(PaymentChannelRequest)
                    .where(
                        PaymentChannelRequest.payment_order_id == order.id,
                        PaymentChannelRequest.operation == "payment_submit",
                    )
                    .order_by(
                        PaymentChannelRequest.created_at.desc(), PaymentChannelRequest.id.desc()
                    )
                    .limit(1)
                )
                if order.status == "closing" or not authorized or self.clock() >= order.expires_at:
                    if prior is None:
                        self._closed(db, order, lease)
                    else:
                        order.status, order.updated_at = "closing", self.clock()
                        ensure_task(
                            db, "payment_close", order.id, now=self.clock(), reactivate=True
                        )
                        complete_task(db, lease, now=self.clock())
                    db.commit()
                    return
                if order.status == "payable" and order.prepay_token:
                    complete_task(db, lease, now=self.clock())
                    db.commit()
                    return
                if prior is not None:
                    not_paid = db.scalar(
                        select(PaymentChannelRequest.id)
                        .where(
                            PaymentChannelRequest.payment_order_id == order.id,
                            PaymentChannelRequest.operation == "payment_query",
                            PaymentChannelRequest.outcome == "verified_response",
                            PaymentChannelRequest.created_at >= prior.created_at,
                            or_(
                                PaymentChannelRequest.error_code.in_(
                                    ("ORDER_NOT_EXIST", "ORDER_NOT_EXISTS")
                                ),
                                (
                                    PaymentChannelRequest.error_code.is_(None)
                                    & (
                                        PaymentChannelRequest.response_snapshot[
                                            "channel_status"
                                        ].as_string()
                                        == "NOTPAY"
                                    )
                                ),
                            ),
                        )
                        .limit(1)
                    )
                    if not_paid is None:
                        ensure_task(
                            db, "payment_query", order.id, now=self.clock(), reactivate=True
                        )
                        complete_task(db, lease, now=self.clock())
                        db.commit()
                        return
                request = self._request(db, order)
                db.commit()
            ratio = perform_channel_call(
                self.factory,
                operation="maximum_ratio",
                target_id=request.merchant_binding_id,
                request_snapshot={"merchant_no": request.merchant_no},
                diagnostic_request_id=new_id(),
                call=lambda: self.profit_sharing.maximum_ratio(merchant_no=request.merchant_no),
                snapshot=lambda value: value,
                lease=lease,
                clock=self.clock,
            )
            with self.factory() as db:
                repo = OrdersRepository(db)
                order, authorized = repo.guard_order(lease.target_id)
                if self._terminal(db, order, lease):
                    return
                require_current_lease(db, lease, now=self.clock())
                if order.status == "closing" or not authorized or self.clock() >= order.expires_at:
                    ensure_task(db, "payment_close", order.id, now=self.clock(), reactivate=True)
                    complete_task(db, lease, now=self.clock())
                    db.commit()
                    return
                items = list(
                    db.scalars(
                        select(ProfitSharingRuleVersionItem).where(
                            ProfitSharingRuleVersionItem.rule_version_id == order.rule_version_id
                        )
                    )
                )
                binding = repo.binding(order)
                if (
                    request.provider_no != self.settings.wechatpay_service_provider_merchant_no
                    or not ConfigurationRepository(db).receiver_ready(
                        binding.id, self.settings.wechatpay_service_provider_merchant_no
                    )
                ):
                    self._prevent_sending(db, order, lease)
                    db.commit()
                    return
                try:
                    if ratio.response.value["merchant_no"] != request.merchant_no:
                        raise WechatPayError("MERCHANT_MISMATCH")
                    validate_amount(
                        order.amount_cents, items, ratio.response.value["maximum_ratio_bps"]
                    )
                except AppError:
                    self._prevent_sending(db, order, lease)
                    db.commit()
                    return
                # Commit send intent together with the current authorization and lease check.
                # A competing close can now only use channel evidence, never the unsent shortcut.
                record = start_request(
                    db,
                    operation="payment_submit",
                    target_id=order.id,
                    request_snapshot=request.snapshot("payment_submit"),
                    request_id=new_id(),
                    now=self.clock(),
                )
                record_id = record.id
                order.status, order.updated_at = "unknown", self.clock()
                db.commit()
            try:
                response = self.payments.create_order(
                    merchant_no=request.merchant_no,
                    order_no=request.order_no,
                    payer_openid=request.payer_openid,
                    amount_cents=request.amount_cents,
                    expires_at=request.expires_at,
                )
            except WechatPayError as error:
                self._save_submit(record_id, error=error)
                raise
            self._save_submit(record_id, response=response)
            with self.factory() as db:
                repo = OrdersRepository(db)
                order, authorized = repo.guard_order(lease.target_id)
                if self._terminal(db, order, lease):
                    return
                now = self.clock()
                require_current_lease(db, lease, now=now)
                order.prepay_token = response.value.prepay_token
                if order.status == "closing" or not authorized or now >= order.expires_at:
                    order.status = "closing"
                    ensure_task(db, "payment_close", order.id, now=now, reactivate=True)
                else:
                    order.status = "payable"
                order.updated_at = now
                ensure_task(
                    db,
                    "payment_query",
                    order.id,
                    now=now,
                    next_run_at=now + timedelta(seconds=30),
                    reactivate=True,
                )
                complete_task(db, lease, now=now)
                db.commit()
        except PaymentConfirmationError as error:
            self._quarantine(lease, error.code)
        except WechatPayError as error:
            self._failed(lease, error)

    def _save_submit(
        self,
        record_id: str,
        *,
        response: ChannelResponse[PrepayResult] | None = None,
        error: WechatPayError | None = None,
    ) -> None:
        with self.factory() as db:
            if error is not None:
                save_response(
                    db,
                    record_id,
                    outcome=error.outcome,
                    now=self.clock(),
                    http_status=error.http_status,
                    channel_request_id=error.channel_request_id,
                    error_code=error.code,
                )
            else:
                assert response is not None
                save_response(
                    db,
                    record_id,
                    outcome="verified_response",
                    now=self.clock(),
                    http_status=response.http_status,
                    channel_request_id=response.channel_request_id,
                    response_snapshot=response.value.snapshot(),
                )
            db.commit()

    def _query(self, lease: TaskLease) -> tuple[OrderRequest, PaymentFact, str] | None:
        if self._success(lease.target_id, lease):
            return None
        with self.factory() as db:
            repo = OrdersRepository(db)
            order, _ = repo.guard_order(lease.target_id)
            if self._terminal(db, order, lease):
                return None
            require_current_lease(db, lease, now=self.clock())
            request = self._request(db, order)
            db.commit()
        result = perform_channel_call(
            self.factory,
            operation="payment_query",
            target_id=request.id,
            request_snapshot=request.snapshot("payment_query"),
            diagnostic_request_id=new_id(),
            call=lambda: self.payments.query_order(
                merchant_no=request.merchant_no, order_no=request.order_no
            ),
            snapshot=PaymentFact.snapshot,
            lease=lease,
            clock=self.clock,
        )
        fact = result.response.value
        if (
            fact.order_no != request.order_no
            or fact.merchant_no != request.merchant_no
            or fact.service_provider_merchant_no != request.provider_no
            or fact.app_id != self.settings.wechat_miniapp_app_id
        ):
            raise PaymentConfirmationError("payment.identity_mismatch")
        if fact.channel_status == "SUCCESS":
            self.confirmation.confirm(
                request.id, fact, lease=lease, source_request_id=result.request_record_id
            )
            return None
        return request, fact, result.request_record_id

    def query(self, lease: TaskLease) -> None:
        try:
            result = self._query(lease)
            if result is None:
                return
            _, fact, _ = result
            with self.factory() as db:
                repo = OrdersRepository(db)
                order, authorized = repo.guard_order(lease.target_id)
                if self._terminal(db, order, lease):
                    return
                now = self.clock()
                require_current_lease(db, lease, now=now)
                if fact.channel_status in {"CLOSED", "REVOKED"}:
                    self._closed(db, order, lease)
                elif fact.channel_status == "REFUND":
                    pause_task(db, lease, now=now, error_code="UNSUPPORTED_REFUND")
                elif order.status == "closing" or not authorized or now >= order.expires_at:
                    order.status, order.updated_at = "closing", now
                    ensure_task(db, "payment_close", order.id, now=now, reactivate=True)
                    reschedule_task(db, lease, now=now, next_run_at=now + timedelta(seconds=30))
                else:
                    if fact.channel_status == "NOTPAY" and not order.prepay_token:
                        ensure_task(db, "payment_submit", order.id, now=now, reactivate=True)
                    reschedule_task(db, lease, now=now, next_run_at=now + timedelta(seconds=30))
                db.commit()
        except PaymentConfirmationError as error:
            self._quarantine(lease, error.code)
        except WechatPayError as error:
            self._failed(lease, error)

    def close(self, lease: TaskLease) -> None:
        try:
            # Only an order with no send intent can be closed without channel evidence.
            with self.factory() as db:
                repo = OrdersRepository(db)
                order, _ = repo.guard_order(lease.target_id)
                if self._terminal(db, order, lease):
                    return
                require_current_lease(db, lease, now=self.clock())
                prior = db.scalar(
                    select(PaymentChannelRequest.id)
                    .where(
                        PaymentChannelRequest.payment_order_id == order.id,
                        PaymentChannelRequest.operation == "payment_submit",
                    )
                    .limit(1)
                )
                if prior is None and not repo.awaiting_posting(
                    order, app_id=self.settings.wechat_miniapp_app_id
                ):
                    self._closed(db, order, lease)
                    db.commit()
                    return
                db.commit()
            result = self._query(lease)
            if result is None:
                return
            request, fact, _ = result
            if fact.channel_status in {"CLOSED", "REVOKED"}:
                with self.factory() as db:
                    order, _ = OrdersRepository(db).guard_order(lease.target_id)
                    self._closed(db, order, lease)
                    db.commit()
                return
            if fact.channel_status != "NOTPAY":
                with self.factory() as db:
                    OrdersRepository(db).guard_order(lease.target_id)
                    require_current_lease(db, lease, now=self.clock())
                    reschedule_task(
                        db,
                        lease,
                        now=self.clock(),
                        next_run_at=self.clock() + timedelta(seconds=30),
                        error_code="PAYMENT_IN_PROGRESS",
                    )
                    db.commit()
                return
            perform_channel_call(
                self.factory,
                operation="payment_close",
                target_id=request.id,
                request_snapshot=request.snapshot("payment_close"),
                diagnostic_request_id=new_id(),
                call=lambda: self.payments.close_order(
                    merchant_no=request.merchant_no, order_no=request.order_no
                ),
                snapshot=lambda _: {"channel_status": "CLOSED"},
                lease=lease,
                clock=self.clock,
            )
            with self.factory() as db:
                order, _ = OrdersRepository(db).guard_order(lease.target_id)
                self._closed(db, order, lease)
                db.commit()
        except PaymentConfirmationError as error:
            self._quarantine(lease, error.code)
        except WechatPayError as error:
            self._failed(lease, error)

    def scan(self, *, limit: int = 100) -> int:
        if not 1 <= limit <= 1000:
            raise ValueError("Invalid payment scan bound")
        with self.factory() as db:
            ids = list(
                db.scalars(
                    select(PaymentOrder.id)
                    .where(
                        PaymentOrder.status.not_in(("succeeded", "closed")),
                    )
                    .order_by(PaymentOrder.updated_at, PaymentOrder.id)
                    .limit(limit)
                )
            )
        count = 0
        for order_id in ids:
            with self.factory() as db:
                repo = OrdersRepository(db)
                order, authorized = repo.guard_order(order_id)
                if order.status in {"succeeded", "closed"}:
                    continue
                now = self.clock()
                awaiting = repo.awaiting_posting(order, app_id=self.settings.wechat_miniapp_app_id)
                if not awaiting and (
                    order.status == "closing" or now >= order.expires_at or not authorized
                ):
                    order.status = "closing"
                    ensure_task(db, "payment_close", order.id, now=now, reactivate=True)
                ensure_task(db, "payment_query", order.id, now=now, reactivate=True)
                order.updated_at = now  # Rotate the bounded scan so later orders cannot starve.
                db.commit()
                count += 1
        return count
