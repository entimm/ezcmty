import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from backend_app.integrations.wechatpay.client import (
    ChannelResponse,
    WechatPayClient,
    WechatPayError,
    identity_digest,
    text_value,
)

type StatementType = Literal["trade", "profit_sharing", "platform_fundflow"]


@dataclass(frozen=True)
class StatementSource:
    hash_type: str
    source_digest: str
    download_url: str = field(repr=False)

    def snapshot(self) -> dict[str, Any]:
        return {"hash_type": self.hash_type, "source_digest": self.source_digest}


@dataclass(frozen=True)
class ParsedStatement:
    statement_type: StatementType
    rows: tuple[dict[str, Any], ...] = field(repr=False)
    summary: dict[str, Any]


def _source(data: dict[str, Any]) -> StatementSource:
    hash_type = text_value(data, "hash_type", 32)
    digest = text_value(data, "hash_value", 256)
    if hash_type != "SHA1" or not re.fullmatch(r"[a-fA-F0-9]{40}", digest):
        raise WechatPayError("INVALID_STRUCTURE")
    return StatementSource(hash_type, digest.lower(), text_value(data, "download_url", 2048))


def _money(value: str) -> int:
    try:
        if not re.fullmatch(r"-?[0-9]+(?:\.[0-9]{1,2})?", value):
            raise ValueError
        cents = Decimal(value) * 100
        result = int(cents)
        if abs(result) > 9_223_372_036_854_775_807:
            raise ValueError
        return result
    except InvalidOperation, ValueError, OverflowError:
        raise WechatPayError("INVALID_STATEMENT_AMOUNT") from None


def _field(row: dict[str, str], key: str, maximum: int = 256) -> str:
    value = row.get(key, "")
    if not value or len(value) > maximum or any(char in value for char in "\x00\r\n"):
        raise WechatPayError("INVALID_STATEMENT_STRUCTURE")
    return value


def _trade_row(row: dict[str, str]) -> dict[str, Any]:
    # Order amount is distinct from settlement amount and payer cash payment.
    result: dict[str, Any] = {
        "service_provider_merchant_no": _field(row, "商户号", 64),
        "merchant_no": _field(row, "特约商户号", 64),
        "app_id": _field(row, "公众账号ID", 64),
        "order_no": _field(row, "商户订单号", 64),
        "channel_transaction_no": _field(row, "微信订单号", 64),
        "channel_status": _field(row, "交易状态", 32),
        "amount_cents": _money(_field(row, "订单金额")),
        "channel_fee_cents": _money(_field(row, "手续费")),
        "paid_at": _field(row, "交易时间", 32),
        "currency": _field(row, "货币种类", 16),
    }
    if row.get("用户标识"):
        result["payer_identity_digest"] = identity_digest(_field(row, "用户标识", 128))
    return result


def _sharing_row(row: dict[str, str]) -> dict[str, Any]:
    account = _field(row, "分账接收方", 128)
    is_merchant = bool(re.fullmatch(r"[0-9]{6,32}", account))
    return {
        "service_provider_merchant_no": _field(row, "分账发起方", 64),
        "merchant_no": _field(row, "分账方", 64),
        "channel_transaction_no": _field(row, "微信订单号", 64),
        "channel_order_no": _field(row, "微信分账/回退单号", 64),
        "order_no": _field(row, "商户分账/回退单号", 64),
        "channel_detail_no": _field(row, "分账明细单号", 64),
        "receiver_type": "merchant" if is_merchant else "personal",
        "receiver_account": account if is_merchant else None,
        "receiver_identity_digest": None if is_merchant else identity_digest(account),
        "amount_cents": _money(_field(row, "金额")),
        "payment_amount_cents": _money(_field(row, "订单金额")),
        "channel_status": {"成功": "SUCCESS"}.get(
            _field(row, "处理状态", 32), _field(row, "处理状态", 32)
        ),
        "channel_business_type": _field(row, "业务类型", 32),
        "finished_at": _field(row, "分账时间", 32),
    }


def _fundflow_row(row: dict[str, str]) -> dict[str, Any]:
    direction = _field(row, "收支类型", 32)
    amount = _money(_field(row, "收支金额(元)"))
    if direction == "支出":
        amount = -abs(amount)
    elif direction == "收入":
        amount = abs(amount)
    reference = row.get("业务凭证号", "")
    return {
        "channel_record_no": _field(row, "资金流水单号", 128),
        "channel_order_no": _field(row, "微信支付业务单号", 128),
        "channel_detail_no": reference
        if re.fullmatch(r"[A-Za-z0-9_|*@-]{1,128}", reference)
        else None,
        "channel_business_type": _field(row, "业务类型", 64),
        "channel_business_name": _field(row, "业务名称", 64),
        "direction": direction,
        "amount_cents": amount,
        "booked_at": _field(row, "记账时间", 32),
    }


def parse_statement(statement_type: StatementType, content: bytes) -> ParsedStatement:
    """Parse only reconciliation fields; discard names, remarks and raw account identifiers."""
    try:
        text = content.decode("utf-8-sig")
        values = [
            [field.removeprefix("`").strip() for field in row]
            for row in csv.reader(io.StringIO(text), strict=True)
            if row
        ]
    except UnicodeError, csv.Error:
        raise WechatPayError("INVALID_STATEMENT_STRUCTURE") from None
    if len(values) < 3:
        raise WechatPayError("INVALID_STATEMENT_STRUCTURE")
    header = values[0]
    if len(set(header)) != len(header):
        raise WechatPayError("INVALID_STATEMENT_STRUCTURE")
    count_key = {
        "trade": "总交易单数",
        "profit_sharing": "总条数",
        "platform_fundflow": "资金流水总笔数",
    }[statement_type]
    summary_index = next(
        (index for index, row in enumerate(values[1:], 1) if row and row[0] == count_key), None
    )
    if summary_index is None or summary_index != len(values) - 2:
        raise WechatPayError("INVALID_STATEMENT_STRUCTURE")
    summary_header, summary_values = values[-2:]
    if len(summary_header) != len(summary_values) or not summary_values[0].isdigit():
        raise WechatPayError("INVALID_STATEMENT_STRUCTURE")
    count = int(summary_values[0])
    if count != summary_index - 1:
        raise WechatPayError("INVALID_STATEMENT_COUNT")
    convert = {
        "trade": _trade_row,
        "profit_sharing": _sharing_row,
        "platform_fundflow": _fundflow_row,
    }[statement_type]
    rows: list[dict[str, Any]] = []
    for values_row in values[1:summary_index]:
        if len(values_row) != len(header):
            raise WechatPayError("INVALID_STATEMENT_STRUCTURE")
        rows.append(convert(dict(zip(header, values_row, strict=True))))
    summary: dict[str, Any] = {"source_row_count": count}
    if statement_type == "trade":
        summary["amount_cents"] = sum(row["amount_cents"] for row in rows)
        summary["channel_fee_cents"] = sum(row["channel_fee_cents"] for row in rows)
    else:
        summary["amount_cents"] = sum(row["amount_cents"] for row in rows)
    return ParsedStatement(statement_type, tuple(rows), summary)


class Statements:
    def __init__(self, client: WechatPayClient) -> None:
        self.client = client

    def request_trade(
        self, *, merchant_no: str, business_date: date
    ) -> ChannelResponse[StatementSource]:
        return self.client.request(
            "GET",
            "/v3/bill/tradebill",
            query={
                "bill_date": business_date.isoformat(),
                "sub_mchid": merchant_no,
                "bill_type": "ALL",
            },
        ).map(_source)

    def request_profit_sharing(
        self,
        *,
        merchant_no: str,
        business_date: date,
    ) -> ChannelResponse[StatementSource]:
        return self.client.request(
            "GET",
            "/v3/profitsharing/bills",
            query={"bill_date": business_date.isoformat(), "sub_mchid": merchant_no},
        ).map(_source)

    def request_platform_fundflow(self, *, business_date: date) -> ChannelResponse[StatementSource]:
        return self.client.request(
            "GET",
            "/v3/bill/fundflowbill",
            query={"bill_date": business_date.isoformat(), "account_type": "BASIC"},
        ).map(_source)

    def download(
        self,
        source: StatementSource,
        *,
        statement_type: StatementType,
    ) -> ChannelResponse[ParsedStatement]:
        if source.hash_type != "SHA1":
            raise WechatPayError("INVALID_DOWNLOAD_SOURCE")
        return self.client.download(source.download_url, source.source_digest).map(
            lambda data: parse_statement(statement_type, data)
        )
