from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any, cast

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend_app.core.config import Settings
from backend_app.core.errors import AppError
from backend_app.core.identifiers import new_id
from backend_app.db.errors import is_unique_violation
from backend_app.domain.client.types import ClientAuthorization
from backend_app.domain.payments.configuration import (
    configuration_reasons,
    fingerprint,
    validate_amount,
)
from backend_app.integrations.wechatpay.client import WechatPayClient
from backend_app.integrations.wechatpay.payments import Payments
from backend_app.models.admin import utc_now
from backend_app.models.payments import BillPaymentReservation, PaymentOrder, PaymentOrderItem
from backend_app.repositories.miniapp import MiniappRepository
from backend_app.repositories.payments.configuration import ConfigurationRepository
from backend_app.repositories.payments.orders import OrdersRepository
from backend_app.repositories.payments.tasks import ensure_task
from backend_app.schemas.payments import resident as schema


class ResidentPaymentService:
    def __init__(
        self,
        db: Session,
        settings: Settings,
        *,
        clock: Callable[[], datetime] = utc_now,
        signer: Payments | None = None,
    ) -> None:
        self.db, self.settings, self.clock, self.signer = db, settings, clock, signer
        self.repo = OrdersRepository(db)
        self.identity = MiniappRepository(db)
        self.configuration = ConfigurationRepository(db)

    def view(self, order: PaymentOrder) -> schema.ResidentPaymentOrder:
        awaiting = self.repo.awaiting_posting(order, app_id=self.settings.wechat_miniapp_app_id)
        terminal = order.status in {"succeeded", "closed"}
        actions: list[schema.AvailableAction] = []
        if not terminal:
            if (
                order.status == "payable"
                and order.prepay_token
                and self.clock() < order.expires_at
                and not awaiting
                and self.repo.authorized(order)
            ):
                actions.append("continue_payment")
            actions.append("refresh")
            if not awaiting:
                actions.append("close")
        return schema.ResidentPaymentOrder(
            id=order.id,
            order_no=order.order_no,
            merchant_name=self.repo.binding(order).merchant_name,
            amount_cents=order.amount_cents,
            payer_total_cents=order.payer_total_cents,
            status=cast(schema.PaymentStatus, order.status),
            confirmation_status="posted"
            if order.status == "succeeded"
            else ("awaiting_posting" if awaiting else "unconfirmed"),
            available_actions=actions,
            items=[
                schema.ResidentPaymentOrderItem(
                    id=item.id,
                    bill_id=item.bill_id,
                    bill_type="property_fee",
                    billing_month=bill.period_start.strftime("%Y-%m"),
                    house_label_snapshot=bill.house_label_snapshot,
                    amount_cents=item.amount_cents,
                )
                for item, bill in self.repo.items(order.id)
            ],
            expires_at=order.expires_at,
            paid_at=order.paid_at,
            closed_at=order.closed_at,
            created_at=order.created_at,
            updated_at=order.updated_at,
        )

    def get(self, ctx: ClientAuthorization, order_id: str) -> schema.ResidentPaymentOrder:
        self.identity.user(ctx.user_id, ctx.version)
        return self.view(self.repo.order(order_id, user_id=ctx.user_id))

    def list(self, ctx: ClientAuthorization, **filters: Any) -> schema.ResidentPaymentOrderPage:
        self.identity.user(ctx.user_id, ctx.version)
        start, end = filters.get("created_at_from"), filters.get("created_at_to")
        if (
            start is not None
            and start.utcoffset() is None
            or end is not None
            and end.utcoffset() is None
        ):
            raise AppError("VALIDATION_ERROR")
        if start is not None and end is not None and start > end:
            raise AppError("VALIDATION_ERROR")
        orders, total = self.repo.list_orders(
            user_id=ctx.user_id,
            app_id=self.settings.wechat_miniapp_app_id,
            **filters,
        )
        return schema.ResidentPaymentOrderPage(
            items=[self.view(order) for order in orders],
            total=total,
            page=filters["page"],
            page_size=filters["page_size"],
        )

    def create(
        self,
        ctx: ClientAuthorization,
        data: schema.ResidentPaymentOrderCreate,
        key: str,
    ) -> schema.ResidentPaymentOrder:
        digest = fingerprint(data.model_dump())
        try:
            self.identity.user(ctx.user_id, ctx.version)
            previous = self.repo.previous(ctx.user_id, key)
            if previous is not None:
                if previous.request_fingerprint != digest:
                    raise AppError("payment.idempotency_conflict")
                return self.view(previous)
            requested = data.items[0]
            guard = self.repo.guard_bill(requested.bill_id, ctx.user_id, exclusive_user=True)
            self.identity.user(ctx.user_id, ctx.version)
            previous = self.repo.previous(ctx.user_id, key)
            if previous is not None:
                if previous.request_fingerprint != digest:
                    raise AppError("payment.idempotency_conflict")
                result = self.view(previous)
                self.db.commit()
                return result
            if not guard.authorized:
                raise AppError("resource.not_found")
            bill = guard.bill
            if bill.row_version != requested.expected_row_version:
                raise AppError("payment.bill_version_conflict")
            if bill.lifecycle_status != "active" or bill.outstanding_cents <= 0:
                raise AppError("payment.bill_not_payable")
            if self.repo.reservation(bill.id) is not None:
                raise AppError("payment.bill_reserved")
            binding, rule, items = self.configuration.current(guard.company.id)
            receiver_ready = binding is not None and self.configuration.receiver_ready(
                binding.id,
                self.settings.wechatpay_service_provider_merchant_no,
            )
            if not self.settings.payment_new_orders_enabled or configuration_reasons(
                guard.company,
                binding,
                rule,
                items,
                settings=self.settings,
                receiver_ready=receiver_ready,
            ):
                raise AppError("payment.configuration_unavailable")
            assert binding is not None and rule is not None and binding.max_ratio_bps is not None
            validate_amount(bill.outstanding_cents, items, binding.max_ratio_bps)
            now = self.clock()
            order = PaymentOrder(
                id=new_id(),
                property_company_id=bill.property_company_id,
                payer_user_id=ctx.user_id,
                merchant_binding_id=binding.id,
                rule_version_id=rule.id,
                order_no="py_" + new_id().replace("-", "")[:29],
                amount_cents=bill.outstanding_cents,
                status="pending",
                expires_at=now + timedelta(minutes=15),
                idempotency_key=key,
                request_fingerprint=digest,
                created_at=now,
                updated_at=now,
            )
            self.db.add(order)
            self.db.flush()
            self.db.add(
                PaymentOrderItem(
                    id=new_id(),
                    property_company_id=bill.property_company_id,
                    payment_order_id=order.id,
                    bill_id=bill.id,
                    amount_cents=order.amount_cents,
                    created_at=now,
                )
            )
            self.db.flush()
            self.db.add(
                BillPaymentReservation(bill_id=bill.id, payment_order_id=order.id, created_at=now)
            )
            self.db.flush()
            ensure_task(self.db, "payment_submit", order.id, now=now)
            ensure_task(
                self.db, "payment_query", order.id, now=now, next_run_at=now + timedelta(seconds=30)
            )
            self.db.commit()
            return self.view(order)
        except IntegrityError as exc:
            self.db.rollback()
            if is_unique_violation(exc, "uq_payment_order_key"):
                previous = self.repo.previous(ctx.user_id, key)
                if previous is not None and previous.request_fingerprint == digest:
                    return self.view(previous)
                raise AppError("payment.idempotency_conflict") from None
            if is_unique_violation(exc, "bill_payment_reservations_pkey"):
                raise AppError("payment.bill_reserved") from None
            raise
        except Exception:
            self.db.rollback()
            raise

    def parameters(
        self, ctx: ClientAuthorization, order_id: str
    ) -> schema.ResidentClientPaymentParameters:
        try:
            self.identity.user(ctx.user_id, ctx.version)
            order, authorized = self.repo.guard_order(order_id, user_id=ctx.user_id)
            self.identity.user(ctx.user_id, ctx.version)
            if not authorized:
                raise AppError("resource.not_found")
            if (
                order.status != "payable"
                or self.clock() >= order.expires_at
                or self.repo.awaiting_posting(
                    order,
                    app_id=self.settings.wechat_miniapp_app_id,
                )
            ):
                raise AppError("payment.order_not_payable")
            if not order.prepay_token:
                raise AppError("payment.parameters_unavailable")
            signer = self.signer or Payments(WechatPayClient.from_settings(self.settings))
            parameters = signer.sign_payment_parameters(order.prepay_token)
            self.db.commit()
            return schema.ResidentClientPaymentParameters(
                payment_order_id=order.id,
                channel="wechat_pay",
                client_parameters=schema.ResidentWechatPayClientParameters.model_validate(
                    parameters
                ),
            )
        except Exception:
            self.db.rollback()
            raise

    def request_recovery(
        self,
        ctx: ClientAuthorization,
        order_id: str,
        *,
        close: bool = False,
    ) -> tuple[schema.ResidentPaymentOrder, bool]:
        try:
            self.identity.user(ctx.user_id, ctx.version)
            order, _ = self.repo.guard_order(order_id, user_id=ctx.user_id)
            self.identity.user(ctx.user_id, ctx.version)
            terminal = order.status in {"succeeded", "closed"}
            if not terminal:
                now = self.clock()
                awaiting = self.repo.awaiting_posting(
                    order, app_id=self.settings.wechat_miniapp_app_id
                )
                if close and not awaiting:
                    order.status, order.updated_at = "closing", now
                    ensure_task(self.db, "payment_close", order.id, now=now, reactivate=True)
                ensure_task(self.db, "payment_query", order.id, now=now, reactivate=True)
            self.db.commit()
            return self.view(order), not terminal
        except Exception:
            self.db.rollback()
            raise
