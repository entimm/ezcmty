import base64
import json
from datetime import UTC, datetime

import httpx
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from tests.support.wechatpay import WechatPayHarness, payment_response

from backend_app.integrations.wechatpay.client import WechatPayError, identity_digest
from backend_app.integrations.wechatpay.payments import Payments, parse_payment


def test_partner_order_freezes_funds_and_preserves_expiry(peer: WechatPayHarness) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/v3/pay/partner/transactions/jsapi"
        body = json.loads(request.content)
        assert body["sp_appid"] == "wx_test_app"
        assert body["sp_mchid"] == "1900000001"
        assert body["sub_mchid"] == "1900000002"
        assert body["payer"] == {"sp_openid": "private-openid"}
        assert body["settle_info"] == {"profit_sharing": True}
        assert body["amount"] == {"total": 10000, "currency": "CNY"}
        assert body["time_expire"] == "2026-10-19T04:15:00+00:00"
        return peer.response({"prepay_id": "private-prepay-token"})

    result = Payments(peer.client(handle)).create_order(
        merchant_no="1900000002",
        order_no="PAY202610190001",
        payer_openid="private-openid",
        amount_cents=10000,
        expires_at=datetime(2026, 10, 19, 4, 15, tzinfo=UTC),
    )
    assert result.value.prepay_token == "private-prepay-token"
    assert "private" not in repr(result)
    assert result.value.snapshot() == {"prepay_available": True}


def test_query_maps_only_safe_facts_and_does_not_infer_channel_fee(peer: WechatPayHarness) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/v3/pay/partner/transactions/out-trade-no/PAY202610190001"
        assert dict(request.url.params) == {"sp_mchid": "1900000001", "sub_mchid": "1900000002"}
        return peer.response(payment_response())

    fact = (
        Payments(peer.client(handle))
        .query_order(merchant_no="1900000002", order_no="PAY202610190001")
        .value
    )
    snapshot = fact.snapshot()
    assert fact.payer_identity_digest == identity_digest("private-payer-openid")
    assert fact.amount_cents == 10000
    assert fact.payer_total_cents == 9900
    assert fact.paid_at == datetime(2026, 10, 19, 4, tzinfo=UTC)
    assert "private-payer-openid" not in json.dumps(snapshot)
    assert "channel_fee_cents" not in snapshot


def test_close_accepts_verified_204_only(peer: WechatPayHarness) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path.endswith("/PAY202610190001/close")
        assert json.loads(request.content) == {"sp_mchid": "1900000001", "sub_mchid": "1900000002"}
        return peer.response(None, 204)

    result = Payments(peer.client(handle)).close_order(
        merchant_no="1900000002", order_no="PAY202610190001"
    )
    assert result.value is None


def test_payment_parameters_use_miniapp_protocol_signature(peer: WechatPayHarness) -> None:
    params = Payments(peer.client(lambda _: peer.response({}))).sign_payment_parameters(
        "prepay-token"
    )
    assert params["signType"] == "RSA"
    assert params["package"] == "prepay_id=prepay-token"
    message = (
        f"wx_test_app\n{params['timeStamp']}\n{params['nonceStr']}\n{params['package']}\n"
    ).encode()
    peer.merchant_key.public_key().verify(
        base64.b64decode(params["paySign"]), message, padding.PKCS1v15(), hashes.SHA256()
    )


@pytest.mark.parametrize(
    "change", ["missing_payer", "bool_amount", "missing_transaction", "currency", "naive_time"]
)
def test_malformed_success_is_not_a_receipt_fact(change: str) -> None:
    data = payment_response()
    if change == "missing_payer":
        del data["payer"]
    elif change == "bool_amount":
        data["amount"]["total"] = True
    elif change == "missing_transaction":
        del data["transaction_id"]
    elif change == "currency":
        data["amount"]["currency"] = "USD"
    else:
        data["success_time"] = "2026-10-19T12:00:00"
    with pytest.raises(WechatPayError):
        parse_payment(data)


def test_unpaid_query_may_omit_success_only_fields() -> None:
    data = {
        "sp_mchid": "1900000001",
        "sub_mchid": "1900000002",
        "sp_appid": "wx_test_app",
        "out_trade_no": "PAY202610190001",
        "trade_state": "NOTPAY",
    }
    fact = parse_payment(data)
    assert fact.amount_cents is None
    assert fact.channel_transaction_no is None
