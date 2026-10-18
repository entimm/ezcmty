import json

import pytest
from tests.support.wechatpay import WechatPayHarness, payment_response

from backend_app.integrations.wechatpay.client import WechatPayError, identity_digest
from backend_app.integrations.wechatpay.notifications import Notifications


def test_raw_signed_body_is_decrypted_and_reduced_to_safe_receipt(peer: WechatPayHarness) -> None:
    raw, headers = peer.notification(payment_response(), "transaction")
    notification = Notifications(peer.client(lambda _: peer.response({}))).payment(headers, raw)
    assert notification.channel_notification_id == "notification-1"
    assert notification.notification_type == "payment_success"
    assert notification.payload["payer_identity_digest"] == identity_digest("private-payer-openid")
    serialized = json.dumps(notification.payload)
    assert "private-payer-openid" not in serialized
    assert "ciphertext" not in serialized
    assert "paySign" not in serialized


def test_reformatted_body_cannot_reuse_original_signature(peer: WechatPayHarness) -> None:
    raw, headers = peer.notification(payment_response(), "transaction")
    changed = json.dumps(json.loads(raw)).encode()
    with pytest.raises(WechatPayError, match="INVALID_SIGNATURE"):
        Notifications(peer.client(lambda _: peer.response({}))).payment(headers, changed)


@pytest.mark.parametrize("change", ["ciphertext", "associated_data", "algorithm", "nonce"])
def test_authenticated_but_invalid_encryption_is_rejected(
    peer: WechatPayHarness, change: str
) -> None:
    raw, _ = peer.notification(payment_response(), "transaction")
    data = json.loads(raw)
    if change == "ciphertext":
        data["resource"]["ciphertext"] = "dGFtcGVyZWQ="
    elif change == "associated_data":
        data["resource"]["associated_data"] = "tampered"
    elif change == "algorithm":
        data["resource"]["algorithm"] = "AES_CBC"
    else:
        data["resource"]["nonce"] = "bad"
    changed = json.dumps(data).encode()
    with pytest.raises(WechatPayError):
        Notifications(peer.client(lambda _: peer.response({}))).payment(
            peer.headers(changed), changed
        )


def test_same_event_name_does_not_mix_payment_and_sharing_routes(peer: WechatPayHarness) -> None:
    data = {
        "sp_mchid": "1900000001",
        "sub_mchid": "1900000002",
        "transaction_id": "tx1",
        "order_id": "sharing1",
        "out_order_no": "PS1",
        "receiver": {"type": "MERCHANT_ID", "account": "1900000001", "amount": 300},
        "success_time": "2026-10-19T12:01:00+08:00",
    }
    raw, headers = peer.notification(data, "profitsharing")
    adapter = Notifications(peer.client(lambda _: peer.response({})))
    with pytest.raises(WechatPayError, match="INVALID_NOTIFICATION"):
        adapter.payment(headers, raw)
    notice = adapter.profit_sharing(headers, raw)
    assert notice.notification_type == "profit_sharing"
    assert notice.payload["receiver_account"] == "1900000001"
    assert notice.payload["amount_cents"] == 300
