from collections.abc import Mapping


class FundsBlocked(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def calculate_allocations(
    amount_cents: int, rates: Mapping[str, int], *, calculation_version: int = 1
) -> dict[str, int]:
    """Apply the frozen, per receiver half-up calculation using integer arithmetic."""
    if calculation_version != 1 or type(amount_cents) is not int or amount_cents <= 0:
        raise ValueError("Unsupported calculation or payment amount")
    if not rates or any(type(rate) is not int or not 0 <= rate <= 10000 for rate in rates.values()):
        raise ValueError("Invalid complete sharing rule")
    if sum(rates.values()) > 10000:
        raise ValueError("Sharing ratio exceeds the payment")
    amounts = {key: (amount_cents * rate + 5000) // 10000 for key, rate in rates.items()}
    if sum(amounts.values()) > amount_cents:
        raise FundsBlocked("ROUNDED_ALLOCATION_EXCEEDS_PAYMENT")
    return {key: amount for key, amount in amounts.items() if amount > 0}


def remaining_allocations(owed: Mapping[str, int], succeeded: Mapping[str, int]) -> dict[str, int]:
    if set(succeeded) - set(owed):
        raise FundsBlocked("SHARING_ALLOCATION_UNKNOWN")
    if any(amount < 0 or amount > owed[key] for key, amount in succeeded.items()):
        raise FundsBlocked("SHARING_OVERFULFILLED")
    return {
        key: amount - succeeded.get(key, 0)
        for key, amount in owed.items()
        if amount > succeeded.get(key, 0)
    }


def retry_seconds(attempt_count: int, retry_after_seconds: int | None = None) -> int:
    interval = min(3600, 5 * (1 << min(max(attempt_count - 1, 0), 10)))
    if retry_after_seconds is not None:
        interval = max(interval, min(3600, max(1, retry_after_seconds)))
    return interval
