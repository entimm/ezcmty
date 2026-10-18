"""Shared evidence checks for the two concrete funds execution use cases."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend_app.domain.payments.funds import FundsBlocked
from backend_app.integrations.wechatpay.profit_sharing import Receiver, SharingFact
from backend_app.models.payments import (
    PaymentChannelRequest,
    PaymentOrder,
    PaymentUnfreezeOrder,
    ProfitSharingOrder,
    ProfitSharingRuleVersionItem,
    PropertyMerchantBinding,
)
from backend_app.repositories.payments.funds import FundsRepository

NOT_FOUND = {"ORDER_NOT_EXIST", "ORDER_NOT_EXISTS", "RESOURCE_NOT_EXISTS", "RESOURCE_NOT_EXIST"}
# Only authenticated, explicit rejections can terminate an unaccepted execution.
REJECTED = {
    "PARAM_ERROR",
    "INVALID_REQUEST",
    "NO_AUTH",
    "NOT_ENOUGH",
    "NOT_ENOUGH_PROFITSHARING",
    "RECEIVER_NOT_EXIST",
    "RECEIVER_NOT_EXISTS",
    "PROFITSHARING_FEE_TOO_HIGH",
    "PROFIT_SHARING_LIMIT_EXCEEDED",
    "RULE_LIMIT",
}
CONFIGURATION_ERRORS = {
    "INVALID_CONFIGURATION",
    "INVALID_REQUEST",
    "KEY_NOT_FOUND",
    "INVALID_KEY",
    "INVALID_PRIVATE_KEY",
    "SIGN_ERROR",
    "NO_AUTH",
    "PARAM_ERROR",
}


@dataclass(frozen=True)
class FundsContext:
    payment_id: str
    execution_id: str
    order_no: str
    merchant_no: str
    channel_transaction_no: str
    receivers: tuple[Receiver, ...] = ()

    def snapshot(self) -> dict[str, object]:
        result: dict[str, object] = {
            "merchant_no": self.merchant_no,
            "channel_transaction_no": self.channel_transaction_no,
            "order_no": self.order_no,
        }
        if self.receivers:
            result["receivers"] = [
                {
                    "receiver_type": receiver.receiver_type,
                    "receiver_account": receiver.receiver_account,
                    "amount_cents": receiver.amount_cents,
                }
                for receiver in self.receivers
            ]
            result["unfreeze_unsplit"] = False
        return result


def execution_context(
    db: Session, payment: PaymentOrder, order: ProfitSharingOrder | PaymentUnfreezeOrder
) -> FundsContext:
    binding = db.get(PropertyMerchantBinding, payment.merchant_binding_id)
    assert binding is not None and payment.channel_transaction_no is not None
    receivers: list[Receiver] = []
    if isinstance(order, ProfitSharingOrder):
        repository = FundsRepository(db)
        allocations = {a.id: a for a in repository.allocations(payment.id)}
        for item in repository.sharing_items(order.id):
            rule = db.get(
                ProfitSharingRuleVersionItem, allocations[item.allocation_id].rule_version_item_id
            )
            assert rule is not None
            receivers.append(Receiver(rule.receiver_account, item.amount_cents, rule.receiver_name))
    return FundsContext(
        payment.id,
        order.id,
        order.order_no,
        binding.merchant_no,
        payment.channel_transaction_no,
        tuple(receivers),
    )


def latest_request(
    db: Session, execution_id: str, *, unfreeze: bool = False
) -> PaymentChannelRequest | None:
    target = (
        PaymentChannelRequest.unfreeze_order_id
        if unfreeze
        else PaymentChannelRequest.profit_sharing_order_id
    )
    return db.scalar(
        select(PaymentChannelRequest)
        .where(target == execution_id)
        .order_by(PaymentChannelRequest.created_at.desc(), PaymentChannelRequest.id.desc())
        .limit(1)
    )


def verify_source(
    db: Session, source_id: str, context: FundsContext, fact: SharingFact, *, unfreeze: bool
) -> None:
    source = db.get(PaymentChannelRequest, source_id)
    operations = (
        {"unfreeze_submit", "unfreeze_query"}
        if unfreeze
        else {"profit_sharing_submit", "profit_sharing_query"}
    )
    target = (
        source.unfreeze_order_id
        if source is not None and unfreeze
        else (source.profit_sharing_order_id if source is not None else None)
    )
    if (
        source is None
        or source.operation not in operations
        or target != context.execution_id
        or source.outcome != "verified_response"
        or source.finished_at is None
        or source.response_snapshot != fact.snapshot()
    ):
        raise FundsBlocked("FUNDS_EVIDENCE_REQUIRED")
    if (
        fact.merchant_no != context.merchant_no
        or fact.order_no != context.order_no
        or fact.channel_transaction_no != context.channel_transaction_no
        or not fact.channel_order_no
        or fact.channel_status not in {"PROCESSING", "FINISHED"}
    ):
        raise FundsBlocked("FUNDS_FACT_MISMATCH")


def verify_receiver_time(fact: SharingFact, *, now: datetime) -> None:
    for receiver in fact.receivers:
        if receiver.channel_status not in {"PENDING", "SUCCESS", "CLOSED"}:
            raise FundsBlocked("FUNDS_FACT_MISMATCH")
        if receiver.channel_status != "PENDING" and (
            receiver.finished_at is None
            or receiver.finished_at.utcoffset() is None
            or receiver.finished_at > now
        ):
            raise FundsBlocked("FUNDS_FACT_MISMATCH")
        if receiver.channel_status == "SUCCESS" and not receiver.channel_detail_no:
            raise FundsBlocked("FUNDS_FACT_MISMATCH")
    if fact.channel_status == "FINISHED" and any(
        receiver.channel_status == "PENDING" for receiver in fact.receivers
    ):
        raise FundsBlocked("FUNDS_FACT_MISMATCH")
