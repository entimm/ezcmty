from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import AfterValidator, BeforeValidator, Field, StringConstraints, model_validator

from backend_app.core.errors import AppError
from backend_app.domain.billing import (
    MAX_CENTS,
    Action,
    AmountSource,
    HouseUsage,
    Lifecycle,
    Settlement,
    calculate_amount,
    clean_optional,
    month_date,
    next_month,
)
from backend_app.domain.billing.calculation import validate_receipt_date as validate_received
from backend_app.domain.billing.creation import BillCreationCommand, InitialBillReceipt
from backend_app.schemas.admin import AdminSchema, Identifier


def checked_month(value: str) -> str:
    next_month(month_date(value))
    return value


Month = Annotated[str, Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$"), AfterValidator(checked_month)]
Money = Annotated[int, Field(strict=True, ge=0, le=MAX_CENTS)]
PositiveMoney = Annotated[int, Field(strict=True, gt=0, le=MAX_CENTS)]
Version = Annotated[int, Field(strict=True, ge=1, le=MAX_CENTS)]
Reason = Annotated[
    str, StringConstraints(strip_whitespace=True), Field(min_length=1, max_length=1000)
]
OptionalReason = Annotated[Reason | None, BeforeValidator(clean_optional)]
External = Annotated[Annotated[str, Field(max_length=128)] | None, BeforeValidator(clean_optional)]
Area = Annotated[str, Field(pattern=r"^(?:0|[1-9]\d{0,7})(?:\.\d{1,4})?$")]
RuleVersion = Annotated[int, Field(strict=True, ge=1, le=32767)]
IdempotencyKey = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")]
Snapshot = Annotated[str, Field(min_length=1, max_length=512)]


def validate_month(value: str) -> None:
    # Reserve an expressible exclusive end date for December bills.
    next_month(month_date(value))


class FeeBasisCreate(AdminSchema):
    expected_latest_version_no: Annotated[int, Field(strict=True, ge=0, le=MAX_CENTS)]
    effective_from_month: Month
    house_usage: HouseUsage
    area_sqm: Area | None = None
    unit_price_cents: Money | None = None
    fixed_amount_cents: Money | None = None
    change_reason: Reason

    @model_validator(mode="after")
    def validate_basis(self) -> Self:
        validate_month(self.effective_from_month)
        area = Decimal(self.area_sqm) if self.area_sqm is not None else None
        if area is not None and area <= 0:
            raise ValueError("Area must be positive")
        calculate_amount(area, self.unit_price_cents, self.fixed_amount_cents)
        return self


class FeeBasisVersion(AdminSchema):
    id: Identifier
    house_id: Identifier
    version_no: Version
    effective_from_month: Month
    house_usage: HouseUsage
    area_sqm: Area | None
    unit_price_cents: Money | None
    fixed_amount_cents: Money | None
    change_reason: Reason
    created_by: Identifier
    created_at: datetime


class FeeCalculationRequest(AdminSchema):
    billing_month: Month

    @model_validator(mode="after")
    def valid_month(self) -> Self:
        validate_month(self.billing_month)
        return self


class FeeCalculation(AdminSchema):
    available: bool
    billing_month: Month
    period_start: date
    period_end: date
    house_label_snapshot: Snapshot
    basis: FeeBasisVersion | None
    calculation_method: Literal["fixed", "area_rate"] | None
    calculation_rule_version: RuleVersion | None
    receivable_cents: Money | None


class InitialReceipt(AdminSchema):
    amount_cents: PositiveMoney
    received_on: date | None = None
    reason: OptionalReason = None

    @model_validator(mode="after")
    def valid_date(self) -> Self:
        try:
            InitialBillReceipt(self.amount_cents, self.received_on, self.reason)
        except AppError as error:
            raise ValueError("Invalid initial receipt") from error
        return self


class BillCreate(AdminSchema):
    house_id: Identifier
    bill_type: Literal["property_fee"] = "property_fee"
    billing_month: Month
    amount_source: AmountSource
    basis_version_id: Identifier | None = None
    expected_calculation_rule_version: RuleVersion | None = None
    expected_receivable_cents: Money | None = None
    receivable_cents: Money | None = None
    manual_amount_reason: OptionalReason = None
    external_bill_no: External = None
    due_date: date | None = None
    initial_receipt: InitialReceipt | None = None

    @model_validator(mode="after")
    def valid_amount_source(self) -> Self:
        try:
            BillCreationCommand.from_input(self.model_dump(mode="json"))
        except AppError as error:
            raise ValueError("Invalid bill creation input") from error
        return self


class BillUpdate(AdminSchema):
    expected_row_version: Version
    external_bill_no: External = None
    due_date: date | None = None

    @model_validator(mode="after")
    def require_change(self) -> Self:
        if not self.model_fields_set - {"expected_row_version"}:
            raise ValueError("At least one change is required")
        return self


class ReceiptCreate(AdminSchema):
    expected_row_version: Version
    amount_cents: PositiveMoney
    received_on: date | None = None
    reason: OptionalReason = None

    @model_validator(mode="after")
    def valid_date(self) -> Self:
        validate_received(self.received_on)
        return self


class ReceiptCorrection(AdminSchema):
    expected_row_version: Version
    corrected_amount_cents: PositiveMoney
    corrected_received_on: date | None
    reason: Reason

    @model_validator(mode="after")
    def valid_date(self) -> Self:
        validate_received(self.corrected_received_on)
        return self


class BillReasonAction(AdminSchema):
    expected_row_version: Version
    reason: Reason


class Bill(AdminSchema):
    id: Identifier
    property_company_id: Identifier
    community_id: Identifier
    house_id: Identifier
    bill_type: Literal["property_fee"]
    period_granularity: Literal["month"]
    billing_month: Month
    period_start: date
    period_end: date
    external_bill_no: External
    basis_version_id: Identifier | None
    amount_source: AmountSource
    calculation_rule_version: RuleVersion | None
    receivable_cents: Money
    settled_cents: Money
    outstanding_cents: Money
    lifecycle_status: Lifecycle
    settlement_status: Settlement | None
    due_date: date | None
    is_overdue: bool
    house_label_snapshot: Snapshot
    manual_amount_reason: OptionalReason
    void_reason: OptionalReason
    voided_at: datetime | None
    voided_by: Identifier | None
    row_version: Version
    created_by: Identifier
    created_at: datetime
    updated_at: datetime
    basis: FeeBasisVersion | None
    house_effective_enabled: bool
    payment_in_progress: bool


class SettlementEntry(AdminSchema):
    id: Identifier
    bill_id: Identifier
    operation_id: Identifier
    entry_type: Literal["receipt", "reversal"]
    source_type: Literal["offline", "online_payment"]
    payment_order_item_id: Identifier | None
    amount_cents: Annotated[int, Field(ge=-MAX_CENTS, le=MAX_CENTS)]
    reverses_entry_id: Identifier | None
    reversed_by_entry_id: Identifier | None
    received_on: date | None
    created_at: datetime
    actor_type: Literal["admin", "system"]
    actor_id: Identifier | None
    actor_name: str
    reason: OptionalReason


class BillOperation(AdminSchema):
    id: Identifier
    bill_id: Identifier
    action: Literal[Action, "online_receipt"]
    bill_version: Version
    actor_type: Literal["admin", "system"]
    actor_id: Identifier | None
    actor_name: str
    reason: OptionalReason
    request_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")]
    created_at: datetime


class BillWriteResult(AdminSchema):
    bill: Bill
    operation: BillOperation
    settlement_entries: list[SettlementEntry]


class BillOperationResult(AdminSchema):
    response_status: int
    result: BillWriteResult


class FeeBasisPage(AdminSchema):
    items: list[FeeBasisVersion]
    total: int
    page: int
    page_size: int


class BillPage(AdminSchema):
    items: list[Bill]
    total: int
    page: int
    page_size: int


class SettlementEntryPage(AdminSchema):
    items: list[SettlementEntry]
    total: int
    page: int
    page_size: int


class BillOperationPage(AdminSchema):
    items: list[BillOperation]
    total: int
    page: int
    page_size: int
