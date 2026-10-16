"""Deterministic billing recipes shared by the size estimate and service executor."""

from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from math import lcm
from typing import Any

from backend_app.domain.billing import RULE_VERSION, Action, calculate_amount
from devtools.seed.config import BillingParameters


def positive_amount(p: BillingParameters, house: int, salt: int) -> int:
    return p.min_receivable_cents + (house * 7919 + salt * 1237) % (
        p.max_receivable_cents - p.min_receivable_cents + 1
    )


@dataclass(frozen=True)
class Basis:
    number: int
    month_index: int
    after_bill: bool
    values: dict[str, Any]
    amount: int


def bases(p: BillingParameters, house: int) -> list[Basis]:
    months = p.months()
    middle = min(max(1, len(months) // 2), len(months) - 1)
    result = []
    for index in range(p.basis_versions_per_house):
        position = 0 if index == 0 else middle if index < 3 else len(months) - 1
        after = index == 2 or (index >= 3 and (position == middle or index > 3))
        amount = positive_amount(p, house, index)
        kind = (
            (house % 3 if p.basis_versions_per_house == 1 else 0)
            if index == 0
            else (2 if index == 3 else 1 if index < 3 else index % 3)
        )
        area, rate, fixed = None, None, None
        if kind == 0:
            # The common range deliberately exercises half-up rounding at the final cent.
            area = str((Decimal(amount) - Decimal("0.5")) / 200) if amount < 20_000_000_000 else "1"
            rate = 200 if amount < 20_000_000_000 else amount
        else:
            fixed = 0 if kind == 2 else amount
        values = {
            "expected_latest_version_no": index,
            "effective_from_month": months[position],
            "house_usage": ("residential", "commercial", "office", "other")[house % 4],
            "area_sqm": area,
            "unit_price_cents": rate,
            "fixed_amount_cents": fixed,
            "change_reason": "开发演示：同月依据纠错，历史账单保持原依据"
            if index == 2
            else "开发演示：新增计费依据",
        }
        result.append(
            Basis(
                index + 1,
                position,
                after,
                values,
                calculate_amount(Decimal(area) if area is not None else None, rate, fixed),
            )
        )
    return result


@dataclass(frozen=True)
class Recipe:
    ordinal: int
    month: str
    state: str
    basis: Basis | None
    amount: int
    automatic: bool
    zero: bool
    initial_full: bool
    initial: bool
    receipts: int
    amount_corrections: int
    date_corrections: int
    reversals: int
    rebuilds: int

    def counts(self) -> dict[str, int]:
        return {
            "bills": 1 + self.rebuilds,
            "bill_operations": 1
            + 2 * self.rebuilds
            + self.receipts
            + self.amount_corrections
            + self.date_corrections
            + 2 * self.reversals
            + int(self.state == "voided"),
            "bill_settlement_entries": int(self.initial)
            + self.receipts
            + 2 * (self.amount_corrections + self.date_corrections + self.reversals),
        }


def recipes(p: BillingParameters, house: int) -> list[Recipe]:
    months = p.months()
    versions = bases(p, house)
    count = p.bill_months_per_house if p.bill_months_per_house is not None else len(months)
    states = (
        ("unpaid", p.unpaid_weight),
        ("partially_settled", p.partially_settled_weight),
        ("settled", p.settled_weight),
        ("voided", p.voided_weight),
    )
    total = sum(weight for _, weight in states)
    result = []
    for index, month in enumerate(months[:count]):
        ordinal = house * len(months) + index
        slot = (ordinal + house) % total
        state = ""
        for name, weight in states:
            if slot < weight:
                state = name
                break
            slot -= weight
        available = [
            v
            for v in versions
            if v.month_index < index or (v.month_index == index and not v.after_bill)
        ]
        basis = max(available, key=lambda v: (v.month_index, v.number), default=None)
        zero = state == "settled" and (ordinal % 4 == 0 or basis is not None and basis.amount == 0)
        automatic = (
            basis is not None
            and (basis.amount == 0 if zero else basis.amount > 0)
            and ordinal % 3 != 1
        )
        if zero and basis is not None and basis.amount == 0:
            automatic = True
        amount = (
            0 if zero else basis.amount if automatic and basis else positive_amount(p, house, index)
        )
        paid = state in {"partially_settled", "settled"} and not zero
        initial_full = (
            paid
            and state == "settled"
            and (ordinal % 2 == 0 or p.additional_receipts_per_bill == 0)
        )
        receipts = p.additional_receipts_per_bill if paid and not initial_full else 0
        initial = paid and (initial_full or receipts == 0 or ordinal % 2 == 0)
        result.append(
            Recipe(
                ordinal,
                month,
                state,
                basis,
                amount,
                automatic,
                zero,
                initial_full,
                initial,
                receipts,
                p.amount_corrections_per_bill if paid and not initial_full else 0,
                p.date_corrections_per_bill if paid else 0,
                p.reversals_per_bill if state in {"unpaid", "partially_settled"} else 0,
                p.rebuilds_per_bill if state == "unpaid" else 0,
            )
        )
    return result


@dataclass(frozen=True)
class Write:
    action: Action
    values: dict[str, Any]
    receipt_from: int | None = None


def writes(recipe: Recipe, today: date) -> list[Write]:
    r = recipe
    due = (today - timedelta(days=15), today + timedelta(days=30), None)[r.ordinal % 3]
    create: dict[str, Any] = {
        "billing_month": r.month,
        "amount_source": "basis" if r.automatic else "manual",
        "external_bill_no": f"000-DEMO-{r.ordinal:06d}" if r.ordinal % 2 == 0 else None,
        "due_date": due.isoformat() if due else None,
    }
    if r.automatic:
        create.update(
            expected_calculation_rule_version=RULE_VERSION, expected_receivable_cents=r.amount
        )
    else:
        create.update(
            receivable_cents=r.amount, manual_amount_reason="开发演示：独立手填金额，不绑定依据"
        )
    target = (
        r.amount if r.state == "settled" else r.amount // 2 if r.state == "partially_settled" else 0
    )
    pieces = r.receipts + int(r.initial)
    amounts = [target // pieces] * pieces if pieces else []
    if amounts:
        amounts[-1] += target - sum(amounts)
    corrected = amounts[-1] if amounts else 0
    if amounts and r.amount_corrections % 2:
        amounts[-1] -= 1
    original_date = None if r.ordinal % 3 == 0 else (today - timedelta(days=10)).isoformat()
    if r.initial:
        create["initial_receipt"] = {
            "amount_cents": amounts[0],
            "received_on": original_date,
            "reason": "开发演示：建账时登记已缴",
        }
    result: list[Write] = []
    version = 0

    def add(action: Action, values: dict[str, Any], receipt_from: int | None = None) -> int:
        nonlocal version
        if action == "create":
            version = 1
        else:
            values = {"expected_row_version": version, **values}
            version += 1
        result.append(Write(action, dict(values), receipt_from))
        return len(result) - 1

    last_receipt = add("create", create)
    for _ in range(r.rebuilds):
        add("void", {"reason": "开发演示：无收款账单作废后重建"})
        add("create", create)
    for amount in amounts[int(r.initial) :]:
        last_receipt = add(
            "receipt",
            {
                "amount_cents": amount,
                "received_on": original_date,
                "reason": "开发演示：后续追加线下收款",
            },
        )
    for index in range(r.amount_corrections):
        amount = corrected - ((r.amount_corrections - index - 1) % 2)
        last_receipt = add(
            "correct_receipt",
            {
                "corrected_amount_cents": amount,
                "corrected_received_on": original_date,
                "reason": "开发演示：金额登记纠错，完整冲正后重新登记",
            },
            last_receipt,
        )
    for index in range(r.date_corrections):
        last_receipt = add(
            "correct_receipt",
            {
                "corrected_amount_cents": corrected,
                "corrected_received_on": (today - timedelta(days=2 + index % 2)).isoformat(),
                "reason": "开发演示：收款日期纠错，金额不变",
            },
            last_receipt,
        )
    for _ in range(r.reversals):
        mistake = add(
            "receipt",
            {
                "amount_cents": min(100, r.amount - target),
                "received_on": None,
                "reason": "开发演示：误登记，下一操作撤销；不代表真实收款",
            },
        )
        add("reverse_receipt", {"reason": "开发演示：撤销误登记，不表示退款"}, mistake)
    if r.state == "voided":
        add("void", {"reason": "开发演示：无有效收款的账单作废"})
    return result


def estimate(p: BillingParameters, houses: int) -> dict[str, int]:
    # Counts repeat independently of generated monetary values. Bound planning work by the cycle.
    total = p.unpaid_weight + p.partially_settled_weight + p.settled_weight + p.voided_weight
    cycle = lcm(total, 12)
    repetitions, remainder = divmod(houses, cycle)
    counts: Counter[str] = Counter()
    for house in range(min(cycle, houses)):
        multiplier = repetitions + int(house < remainder)
        for recipe in recipes(p, house):
            for key, value in recipe.counts().items():
                counts[key] += value * multiplier
    return {
        "property_fee_basis_versions": houses * p.basis_versions_per_house,
        "bills": counts["bills"],
        "bill_operations": counts["bill_operations"],
        "bill_settlement_entries": counts["bill_settlement_entries"],
    }
