import pytest

from backend_app.domain.payments.funds import (
    FundsBlocked,
    calculate_allocations,
    remaining_allocations,
    retry_seconds,
)


@pytest.mark.parametrize(
    ("amount", "rate", "expected"),
    [
        (1, 4999, {}),
        (1, 5000, {"receiver": 1}),
        (3, 5000, {"receiver": 2}),
        (10000, 300, {"receiver": 300}),
        (10000, 0, {}),
    ],
)
def test_half_up_uses_order_amount_and_keeps_only_positive_allocations(
    amount: int, rate: int, expected: dict[str, int]
) -> None:
    assert calculate_allocations(amount, {"receiver": rate}) == expected


def test_receivers_are_rounded_independently_and_sum_is_checked() -> None:
    assert calculate_allocations(3, {"a": 1667, "b": 1667}) == {"a": 1, "b": 1}
    with pytest.raises(FundsBlocked, match="ROUNDED_ALLOCATION_EXCEEDS_PAYMENT"):
        calculate_allocations(1, {"a": 5000, "b": 5000})


def test_remaining_uses_successful_receipts_without_counting_failed_attempts() -> None:
    assert remaining_allocations({"a": 300, "b": 200}, {"a": 300}) == {"b": 200}
    with pytest.raises(FundsBlocked, match="SHARING_OVERFULFILLED"):
        remaining_allocations({"a": 300}, {"a": 301})


@pytest.mark.parametrize("attempt", [1, 10, 10000])
def test_retry_delay_is_bounded_and_respects_channel_hint(attempt: int) -> None:
    assert 30 <= retry_seconds(attempt, 30) <= 3600
