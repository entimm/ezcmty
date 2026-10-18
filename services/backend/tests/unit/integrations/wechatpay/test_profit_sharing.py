import base64
import json

import httpx
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from tests.support.wechatpay import WechatPayHarness, sharing_response

from backend_app.integrations.wechatpay.client import WechatPayError
from backend_app.integrations.wechatpay.profit_sharing import (
    ProfitSharing,
    Receiver,
    SharingFact,
    parse_sharing,
)


def test_durable_sharing_fact_round_trip_checks_each_receiver() -> None:
    fact = parse_sharing(sharing_response())
    assert SharingFact.from_snapshot(fact.snapshot()) == fact
    invalid = fact.snapshot()
    invalid["receivers"][0]["finished_at"] = None
    with pytest.raises(WechatPayError, match="INVALID_STRUCTURE"):
        SharingFact.from_snapshot(invalid)


def test_platform_receiver_uses_service_provider_relationship(peer: WechatPayHarness) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["relation_type"] == "SERVICE_PROVIDER"
        assert payload["type"] == "MERCHANT_ID"
        assert payload["name"] != "隔离平台"
        return peer.response(
            {"sub_mchid": "1900000002", "type": "MERCHANT_ID", "account": "1900000001"}
        )

    ProfitSharing(peer.client(handle)).add_receiver(
        merchant_no="1900000002", receiver_account="1900000001", receiver_name="隔离平台"
    )


def test_request_has_encrypted_name_and_keeps_remaining_funds_frozen(
    peer: WechatPayHarness,
) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v3/profitsharing/orders"
        assert request.headers["Wechatpay-Serial"] == "PUB_KEY_ID_TEST"
        body = json.loads(request.content)
        assert body["unfreeze_unsplit"] is False
        assert body["sub_mchid"] == "1900000002"
        assert body["out_order_no"] == "PS202610190001"
        assert body["transaction_id"] == "transaction-1"
        assert body["receivers"][0]["amount"] == 300
        assert (
            peer.platform_key.decrypt(
                base64.b64decode(body["receivers"][0]["name"]),
                padding.OAEP(mgf=padding.MGF1(hashes.SHA1()), algorithm=hashes.SHA1(), label=None),
            ).decode()
            == "平台全称"
        )
        assert "平台全称" not in request.content.decode()
        return peer.response(sharing_response())

    fact = (
        ProfitSharing(peer.client(handle))
        .create_order(
            merchant_no="1900000002",
            channel_transaction_no="transaction-1",
            order_no="PS202610190001",
            receivers=(Receiver("1900000001", 300, "平台全称"),),
        )
        .value
    )
    assert fact.receivers[0].channel_status == "SUCCESS"
    assert "平台全称" not in json.dumps(fact.snapshot())


def test_finished_with_closed_receiver_is_explicit_failure() -> None:
    fact = parse_sharing(sharing_response(result="CLOSED"))
    assert fact.channel_status == "FINISHED"
    assert fact.receivers[0].channel_status == "CLOSED"


def test_closed_receiver_requires_channel_completion_time() -> None:
    data = sharing_response(result="CLOSED")
    del data["receivers"][0]["finish_time"]
    with pytest.raises(WechatPayError, match="INVALID_STRUCTURE"):
        parse_sharing(data)


def test_finished_with_pending_receiver_is_not_consistent_evidence() -> None:
    with pytest.raises(WechatPayError, match="INVALID_STRUCTURE"):
        parse_sharing(sharing_response(result="PENDING"))


def test_unfreeze_uses_independent_endpoint_and_original_query(peer: WechatPayHarness) -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        data = sharing_response()
        data["out_order_no"] = "UF202610190001"
        data["receivers"][0]["account"] = "1900000002"
        data["receivers"][0]["amount"] = 9694
        return peer.response(data)

    adapter = ProfitSharing(peer.client(handle))
    fact = adapter.unfreeze(
        merchant_no="1900000002", channel_transaction_no="transaction-1", order_no="UF202610190001"
    ).value
    assert requests[0].url.path == "/v3/profitsharing/orders/unfreeze"
    assert "amount" not in json.loads(requests[0].content)
    assert fact.receivers[0].amount_cents == 9694
    adapter.query_order(
        merchant_no="1900000002", channel_transaction_no="transaction-1", order_no="UF202610190001"
    )
    assert requests[1].url.path == "/v3/profitsharing/orders/UF202610190001"
    assert dict(requests[1].url.params) == {
        "sub_mchid": "1900000002",
        "transaction_id": "transaction-1",
    }


@pytest.mark.parametrize("operation", ["add", "delete", "ratio", "remaining"])
def test_merchant_capability_protocol_paths(peer: WechatPayHarness, operation: str) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        if operation in {"add", "delete"}:
            path = "add" if operation == "add" else "delete"
            assert request.url.path == "/v3/profitsharing/receivers/" + path
            body = json.loads(request.content)
            assert body["type"] == "MERCHANT_ID"
            assert body["sub_mchid"] == "1900000002"
            if operation == "add":
                assert request.headers["Wechatpay-Serial"] == "PUB_KEY_ID_TEST"
                assert body["name"] != "平台全称"
            return peer.response(
                {
                    "sub_mchid": "1900000002",
                    "type": "MERCHANT_ID",
                    "account": "1900000001",
                    "name": "sensitive-name-must-not-survive",
                }
            )
        if operation == "ratio":
            assert request.url.path == "/v3/profitsharing/merchant-configs/1900000002"
            return peer.response({"sub_mchid": "1900000002", "max_ratio": 3000})
        assert request.url.path == "/v3/profitsharing/transactions/transaction-1/amounts"
        return peer.response({"transaction_id": "transaction-1", "unsplit_amount": 0})

    adapter = ProfitSharing(peer.client(handle))
    if operation == "add":
        value = adapter.add_receiver(
            merchant_no="1900000002", receiver_account="1900000001", receiver_name="平台全称"
        ).value
    elif operation == "delete":
        value = adapter.delete_receiver(
            merchant_no="1900000002", receiver_account="1900000001"
        ).value
    elif operation == "ratio":
        value = adapter.maximum_ratio(merchant_no="1900000002").value
        assert value["maximum_ratio_bps"] == 3000
    else:
        value = adapter.remaining_amount(channel_transaction_no="transaction-1").value
        assert value["remaining_cents"] == 0
    assert "sensitive" not in json.dumps(value)
