import json

from backend_app.integrations.wechatpay.client import identity_digest
from backend_app.integrations.wechatpay.evidence import request_snapshot


def test_payment_attempt_whitelist_protects_credentials_and_payer() -> None:
    snapshot = request_snapshot(
        "payment_submit",
        {
            "order_no": "PAY1",
            "merchant_no": "1900000002",
            "amount_cents": 10000,
            "payer_openid": "private-openid",
            "Authorization": "private-signature",
            "prepay_token": "private-token",
            "description": "private-description",
            "api_v3_key": "private-key",
        },
    )
    assert snapshot == {
        "order_no": "PAY1",
        "merchant_no": "1900000002",
        "amount_cents": 10000,
        "payer_identity_digest": identity_digest("private-openid"),
    }
    assert "private" not in json.dumps(snapshot)


def test_sharing_attempt_whitelist_never_persists_encrypted_or_plain_names() -> None:
    snapshot = request_snapshot(
        "profit_sharing_submit",
        {
            "order_no": "PS1",
            "channel_transaction_no": "tx1",
            "receivers": [
                {
                    "receiver_type": "merchant",
                    "receiver_account": "1900000001",
                    "amount_cents": 300,
                    "receiver_name": "private-name",
                    "name": "private-encrypted",
                }
            ],
        },
    )
    assert snapshot["receivers"] == [
        {"receiver_type": "merchant", "receiver_account": "1900000001", "amount_cents": 300}
    ]
    assert snapshot["unfreeze_unsplit"] is False
    assert "private" not in json.dumps(snapshot)
