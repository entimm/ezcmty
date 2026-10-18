"""Explicit business field whitelist for channel attempt diagnostics."""

from collections.abc import Mapping
from datetime import date, datetime
from typing import Any

from backend_app.integrations.wechatpay.client import WechatPayError, identity_digest

_COMMON = {"service_provider_merchant_no", "merchant_no", "app_id"}
_PAYMENT = _COMMON | {"order_no", "amount_cents", "expires_at", "payer_identity_digest"}
_FUNDS = _COMMON | {"order_no", "channel_transaction_no"}
_MERCHANT = _COMMON | {"receiver_type", "receiver_account", "relation_type"}
_STATEMENT = _COMMON | {"business_date", "statement_type", "hash_type", "source_digest"}
_FIELDS = {
    "payment_submit": _PAYMENT,
    "payment_query": _PAYMENT,
    "payment_close": _PAYMENT,
    "receiver_add": _MERCHANT,
    "receiver_delete": _MERCHANT,
    "maximum_ratio": _COMMON,
    "profit_sharing_submit": _FUNDS,
    "profit_sharing_query": _FUNDS,
    "unfreeze_submit": _FUNDS,
    "unfreeze_query": _FUNDS,
    "remaining_amount": _FUNDS,
    "trade_statement": _STATEMENT,
    "profit_sharing_statement": _STATEMENT,
    "platform_fundflow_statement": _STATEMENT,
    "statement_download": _STATEMENT,
}


def request_snapshot(operation: str, parameters: Mapping[str, Any]) -> dict[str, Any]:
    allowed = _FIELDS.get(operation)
    if allowed is None:
        raise WechatPayError("INVALID_EVIDENCE_OPERATION")
    result: dict[str, Any] = {}
    for key in allowed:
        if key not in parameters:
            continue
        value = parameters[key]
        if isinstance(value, (datetime, date)):
            result[key] = value.isoformat()
        elif value is None or type(value) is int:
            result[key] = value
        elif isinstance(value, str) and len(value) <= 256:
            result[key] = value
        else:
            raise WechatPayError("INVALID_EVIDENCE_VALUE")
    if operation.startswith("payment_") and "payer_openid" in parameters:
        openid = parameters["payer_openid"]
        if not isinstance(openid, str) or not 0 < len(openid) <= 128:
            raise WechatPayError("INVALID_EVIDENCE_VALUE")
        result["payer_identity_digest"] = identity_digest(openid)
    if operation == "profit_sharing_submit":
        receivers = parameters.get("receivers", ())
        if not isinstance(receivers, (tuple, list)) or len(receivers) > 50:
            raise WechatPayError("INVALID_EVIDENCE_VALUE")
        result["receivers"] = []
        for receiver in receivers:
            if not isinstance(receiver, Mapping):
                raise WechatPayError("INVALID_EVIDENCE_VALUE")
            if receiver.get("receiver_type") != "merchant":
                raise WechatPayError("INVALID_EVIDENCE_VALUE")
            result["receivers"].append(
                {
                    key: receiver[key]
                    for key in ("receiver_type", "receiver_account", "amount_cents")
                    if key in receiver
                }
            )
        result["unfreeze_unsplit"] = False
    return result
