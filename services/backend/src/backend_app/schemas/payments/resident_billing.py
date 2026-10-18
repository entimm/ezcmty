from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import Field, field_validator

from backend_app.schemas.admin import Identifier
from backend_app.schemas.payments.base import PaymentSchema

type ResidentPaymentAmount = Annotated[int, Field(ge=0, le=9007199254740991, strict=True)]

type ResidentPaymentTimestamp = Annotated[datetime, Field(json_schema_extra={"pattern": "Z$"})]


class ResidentBill(PaymentSchema):
    id: Identifier
    property_company_id: Identifier
    property_company_name: Annotated[str, Field(min_length=1, max_length=200)]
    community_id: Identifier
    house_id: Identifier
    house_label_snapshot: Annotated[str, Field(min_length=1, max_length=512)]
    bill_type: Literal["property_fee"]
    billing_month: Annotated[str, Field(pattern="^\\d{4}-(0[1-9]|1[0-2])$")]
    period_start: date
    period_end: date
    receivable_cents: ResidentPaymentAmount
    settled_cents: ResidentPaymentAmount
    outstanding_cents: ResidentPaymentAmount
    lifecycle_status: Literal["active", "voided"]
    settlement_status: Literal["unpaid", "partially_settled", "settled"] | None
    due_date: date | None
    is_overdue: bool
    row_version: Annotated[int, Field(ge=1, le=9007199254740991, strict=True)]
    payment_availability: Literal[
        "available",
        "own_payment_in_progress",
        "other_payment_in_progress",
        "settled",
        "voided",
        "collection_unavailable",
    ]
    own_payment_order_id: Identifier | None
    created_at: ResidentPaymentTimestamp
    updated_at: ResidentPaymentTimestamp


class ResidentBillPage(PaymentSchema):
    items: Annotated[list[ResidentBill], Field(max_length=100)]
    total: Annotated[int, Field(ge=0, le=9007199254740991, strict=True)]
    page: Annotated[int, Field(ge=1, le=9007199254740991, strict=True)]
    page_size: Annotated[int, Field(ge=1, le=100, strict=True)]


class ResidentBillSettlementEntry(PaymentSchema):
    id: Identifier
    bill_id: Identifier
    entry_type: Literal["receipt", "reversal"]
    source_type: Literal["offline", "online_payment"]
    amount_cents: Annotated[
        int,
        Field(
            ge=-9007199254740991,
            le=9007199254740991,
            strict=True,
            json_schema_extra={"not": {"const": 0}},
        ),
    ]
    received_on: date | None
    display_type: Literal["own_payment", "other_payment", "offline_receipt", "offline_adjustment"]
    own_payment_order_id: Identifier | None
    created_at: ResidentPaymentTimestamp

    @field_validator("amount_cents")
    @classmethod
    def nonzero_amount(cls, value: int) -> int:
        if value == 0:
            raise ValueError("Settlement entries cannot be zero")
        return value


class ResidentBillSettlementEntryPage(PaymentSchema):
    items: Annotated[list[ResidentBillSettlementEntry], Field(max_length=100)]
    total: Annotated[int, Field(ge=0, le=9007199254740991, strict=True)]
    page: Annotated[int, Field(ge=1, le=9007199254740991, strict=True)]
    page_size: Annotated[int, Field(ge=1, le=100, strict=True)]
