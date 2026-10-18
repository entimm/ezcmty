from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from urllib.parse import quote

from backend_app.integrations.wechatpay.client import (
    ChannelResponse,
    WechatPayClient,
    WechatPayError,
    cents_value,
    object_value,
    text_value,
    timestamp_value,
)


@dataclass(frozen=True)
class Receiver:
    receiver_account: str
    amount_cents: int
    receiver_name: str = field(repr=False)
    description: str = "平台服务费"
    receiver_type: str = "merchant"


@dataclass(frozen=True)
class ReceiverFact:
    receiver_type: str
    receiver_account: str
    amount_cents: int
    channel_status: str
    channel_detail_no: str | None
    finished_at: datetime | None
    error_code: str | None

    def snapshot(self) -> dict[str, Any]:
        return {
            "receiver_type": self.receiver_type,
            "receiver_account": self.receiver_account,
            "amount_cents": self.amount_cents,
            "channel_status": self.channel_status,
            "channel_detail_no": self.channel_detail_no,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "error_code": self.error_code,
        }


@dataclass(frozen=True)
class SharingFact:
    merchant_no: str
    channel_transaction_no: str
    order_no: str
    channel_order_no: str
    channel_status: str
    receivers: tuple[ReceiverFact, ...]

    @classmethod
    def from_snapshot(cls, data: dict[str, Any]) -> SharingFact:
        """Rebuild persisted authenticated evidence without authenticating new input."""
        receivers = data.get("receivers")
        if not isinstance(receivers, list) or not 1 <= len(receivers) <= 50:
            raise WechatPayError("INVALID_STRUCTURE")
        parsed = []
        for entry in receivers:
            item = object_value(entry)
            if item.get("receiver_type") != "merchant":
                raise WechatPayError("UNSUPPORTED_RECEIVER_TYPE")
            wire = {
                "type": "MERCHANT_ID",
                "account": item.get("receiver_account"),
                "amount": item.get("amount_cents"),
                "result": item.get("channel_status"),
                "detail_id": item.get("channel_detail_no"),
                "finish_time": item.get("finished_at"),
                "fail_reason": item.get("error_code"),
            }
            parsed.append({key: value for key, value in wire.items() if value is not None})
        return parse_sharing(
            {
                "sub_mchid": data.get("merchant_no"),
                "transaction_id": data.get("channel_transaction_no"),
                "out_order_no": data.get("order_no"),
                "order_id": data.get("channel_order_no"),
                "state": data.get("channel_status"),
                "receivers": parsed,
            }
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "merchant_no": self.merchant_no,
            "channel_transaction_no": self.channel_transaction_no,
            "order_no": self.order_no,
            "channel_order_no": self.channel_order_no,
            "channel_status": self.channel_status,
            "receivers": [receiver.snapshot() for receiver in self.receivers],
        }


def parse_receiver(data: dict[str, Any]) -> ReceiverFact:
    # Current product accepts merchant receivers; never expose a personal OpenID in evidence.
    if text_value(data, "type", 32) != "MERCHANT_ID":
        raise WechatPayError("UNSUPPORTED_RECEIVER_TYPE")
    status = text_value(data, "result", 32)
    if status not in {"PENDING", "SUCCESS", "CLOSED"}:
        raise WechatPayError("INVALID_STRUCTURE")
    finished_at = (
        timestamp_value(text_value(data, "finish_time", 64)) if data.get("finish_time") else None
    )
    detail_no = text_value(data, "detail_id", 64) if data.get("detail_id") else None
    if status in {"SUCCESS", "CLOSED"} and finished_at is None:
        raise WechatPayError("INVALID_STRUCTURE")
    if status == "SUCCESS" and detail_no is None:
        raise WechatPayError("INVALID_STRUCTURE")
    return ReceiverFact(
        "merchant",
        text_value(data, "account", 128),
        cents_value(data, "amount"),
        status,
        detail_no,
        finished_at,
        text_value(data, "fail_reason", 128) if data.get("fail_reason") else None,
    )


def parse_sharing(data: dict[str, Any]) -> SharingFact:
    status = text_value(data, "state", 32)
    receivers = data.get("receivers")
    if status not in {"PROCESSING", "FINISHED"} or not isinstance(receivers, list):
        raise WechatPayError("INVALID_STRUCTURE")
    if not 1 <= len(receivers) <= 50:
        raise WechatPayError("INVALID_STRUCTURE")
    facts = tuple(parse_receiver(object_value(receiver)) for receiver in receivers)
    if len({(fact.receiver_type, fact.receiver_account) for fact in facts}) != len(facts):
        raise WechatPayError("INVALID_STRUCTURE")
    if status == "FINISHED" and any(fact.channel_status == "PENDING" for fact in facts):
        raise WechatPayError("INVALID_STRUCTURE")
    return SharingFact(
        text_value(data, "sub_mchid", 64),
        text_value(data, "transaction_id", 64),
        text_value(data, "out_order_no", 64),
        text_value(data, "order_id", 64),
        status,
        facts,
    )


class ProfitSharing:
    def __init__(self, client: WechatPayClient) -> None:
        self.client = client

    def add_receiver(
        self,
        *,
        merchant_no: str,
        receiver_account: str,
        receiver_name: str,
        relation_type: str = "SERVICE_PROVIDER",
    ) -> ChannelResponse[dict[str, Any]]:
        if not receiver_name:
            raise WechatPayError("INVALID_REQUEST")
        response = self.client.request(
            "POST",
            "/v3/profitsharing/receivers/add",
            encrypted=True,
            body={
                "appid": self.client.config.app_id,
                "sub_mchid": merchant_no,
                "type": "MERCHANT_ID",
                "account": receiver_account,
                "name": self.client.encrypt_sensitive(receiver_name),
                "relation_type": relation_type,
            },
        )
        return response.map(self._receiver_identity)

    def delete_receiver(
        self,
        *,
        merchant_no: str,
        receiver_account: str,
    ) -> ChannelResponse[dict[str, Any]]:
        return self.client.request(
            "POST",
            "/v3/profitsharing/receivers/delete",
            body={
                "appid": self.client.config.app_id,
                "sub_mchid": merchant_no,
                "type": "MERCHANT_ID",
                "account": receiver_account,
            },
        ).map(self._receiver_identity)

    def maximum_ratio(self, *, merchant_no: str) -> ChannelResponse[dict[str, Any]]:
        response = self.client.request(
            "GET",
            "/v3/profitsharing/merchant-configs/" + quote(merchant_no, safe=""),
        )
        data = response.value
        ratio = cents_value(data, "max_ratio")
        if ratio > 10000:
            raise WechatPayError("INVALID_STRUCTURE")
        return response.map(
            lambda _: {
                "merchant_no": text_value(data, "sub_mchid", 64),
                "maximum_ratio_bps": ratio,
            }
        )

    def create_order(
        self,
        *,
        merchant_no: str,
        channel_transaction_no: str,
        order_no: str,
        receivers: tuple[Receiver, ...],
    ) -> ChannelResponse[SharingFact]:
        if not 1 <= len(receivers) <= 50:
            raise WechatPayError("INVALID_REQUEST")
        items: list[dict[str, Any]] = []
        seen: set[str] = set()
        for receiver in receivers:
            if (
                receiver.receiver_type != "merchant"
                or receiver.receiver_account in seen
                or not receiver.receiver_name
                or type(receiver.amount_cents) is not int
                or not 0 < receiver.amount_cents <= 2_147_483_647
            ):
                raise WechatPayError("INVALID_REQUEST")
            seen.add(receiver.receiver_account)
            items.append(
                {
                    "type": "MERCHANT_ID",
                    "account": receiver.receiver_account,
                    "name": self.client.encrypt_sensitive(receiver.receiver_name),
                    "amount": receiver.amount_cents,
                    "description": receiver.description,
                }
            )
        return self.client.request(
            "POST",
            "/v3/profitsharing/orders",
            encrypted=True,
            body={
                "appid": self.client.config.app_id,
                "sub_mchid": merchant_no,
                "transaction_id": channel_transaction_no,
                "out_order_no": order_no,
                "receivers": items,
                "unfreeze_unsplit": False,
            },
        ).map(parse_sharing)

    def query_order(
        self,
        *,
        merchant_no: str,
        channel_transaction_no: str,
        order_no: str,
    ) -> ChannelResponse[SharingFact]:
        return self.client.request(
            "GET",
            "/v3/profitsharing/orders/" + quote(order_no, safe=""),
            query={"sub_mchid": merchant_no, "transaction_id": channel_transaction_no},
        ).map(parse_sharing)

    def unfreeze(
        self,
        *,
        merchant_no: str,
        channel_transaction_no: str,
        order_no: str,
    ) -> ChannelResponse[SharingFact]:
        return self.client.request(
            "POST",
            "/v3/profitsharing/orders/unfreeze",
            body={
                "sub_mchid": merchant_no,
                "transaction_id": channel_transaction_no,
                "out_order_no": order_no,
                "description": "账单资金解冻",
            },
        ).map(parse_sharing)

    def remaining_amount(self, *, channel_transaction_no: str) -> ChannelResponse[dict[str, Any]]:
        response = self.client.request(
            "GET",
            "/v3/profitsharing/transactions/" + quote(channel_transaction_no, safe="") + "/amounts",
        )
        return response.map(
            lambda data: {
                "channel_transaction_no": text_value(data, "transaction_id", 64),
                "remaining_cents": cents_value(data, "unsplit_amount"),
            }
        )

    @staticmethod
    def _receiver_identity(data: dict[str, Any]) -> dict[str, Any]:
        if text_value(data, "type", 32) != "MERCHANT_ID":
            raise WechatPayError("INVALID_STRUCTURE")
        return {
            "merchant_no": text_value(data, "sub_mchid", 64),
            "receiver_type": "merchant",
            "receiver_account": text_value(data, "account", 128),
        }
