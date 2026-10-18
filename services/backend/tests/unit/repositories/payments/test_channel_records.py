import pytest

from backend_app.repositories.payments.channel_records import validate_snapshot


@pytest.mark.parametrize(
    "field",
    [
        "Authorization",
        "api_v3_key",
        "private_key",
        "payer_openid",
        "prepay_token",
        "receiver_name",
        "raw_body",
    ],
)
def test_repository_rejects_sensitive_fields_in_channel_snapshots(field: str) -> None:
    with pytest.raises(ValueError, match="whitelist"):
        validate_snapshot({field: "private"})


@pytest.mark.parametrize("value", [1.5, float("nan"), object(), "x" * 1001])
def test_snapshot_values_are_bounded_plain_json(value: object) -> None:
    with pytest.raises(ValueError):
        validate_snapshot({"amount_cents": value})
