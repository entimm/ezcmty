from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal
from zoneinfo import ZoneInfo

MAX_CENTS = 9007199254740991
RULE_VERSION = 1
HouseUsage = Literal["residential", "commercial", "office", "other"]
AmountSource = Literal["basis", "manual"]
Lifecycle = Literal["active", "voided"]
Settlement = Literal["unpaid", "partially_settled", "settled"]
Action = Literal["create", "update", "receipt", "correct_receipt", "reverse_receipt", "void"]


def business_today() -> date:
    return datetime.now(UTC).astimezone(ZoneInfo("Asia/Shanghai")).date()


def validate_receipt_date(value: date | None) -> None:
    if value is not None and value > business_today():
        raise ValueError("Receipt date cannot be in the future")


def month_date(value: str) -> date:
    return date.fromisoformat(value + "-01")


def next_month(value: date) -> date:
    return date(value.year + (value.month == 12), value.month % 12 + 1, 1)


def calculate_amount(area: Decimal | None, rate: int | None, fixed: int | None) -> int:
    if fixed is not None:
        amount = fixed
    else:
        if area is None or rate is None or area <= 0 or rate < 0:
            raise ValueError("Area and rate are required")
        amount = int((area * rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    if not 0 <= amount <= MAX_CENTS:
        raise ValueError("Amount exceeds supported range")
    return amount


def clean_optional(value: object) -> object:
    if isinstance(value, str):
        return value.strip() or None
    return value
