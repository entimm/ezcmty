from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field

from backend_app.schemas.admin import AdminSchema, Identifier
from backend_app.schemas.miniapp import RowVersion
from backend_app.schemas.payments.base import PaymentSchema

type PaymentStatus = Literal["pending", "unknown", "payable", "closing", "succeeded", "closed"]
type ConfirmationStatus = Literal["unconfirmed", "awaiting_posting", "posted"]
type AvailableAction = Literal["continue_payment", "refresh", "close"]
Amount = Annotated[int, Field(ge=0, le=9007199254740991, strict=True)]
PositiveAmount = Annotated[int, Field(ge=1, le=9007199254740991, strict=True)]
Timestamp = Annotated[datetime, Field(json_schema_extra={"pattern": "Z$"})]


class ResidentPaymentItemCreate(AdminSchema):
    bill_id: Identifier
    expected_row_version: RowVersion


class ResidentPaymentOrderCreate(AdminSchema):
    items: Annotated[list[ResidentPaymentItemCreate], Field(min_length=1, max_length=1)]


class ResidentPaymentOrderItem(AdminSchema):
    id: Identifier
    bill_id: Identifier
    bill_type: Literal["property_fee"]
    billing_month: Annotated[str, Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")]
    house_label_snapshot: Annotated[str, Field(min_length=1, max_length=512)]
    amount_cents: PositiveAmount


class ResidentPaymentOrder(PaymentSchema):
    id: Identifier
    order_no: Annotated[str, Field(min_length=1, max_length=64)]
    merchant_name: Annotated[str, Field(min_length=1, max_length=256)]
    amount_cents: PositiveAmount
    payer_total_cents: Amount | None
    status: PaymentStatus
    confirmation_status: ConfirmationStatus
    available_actions: Annotated[
        list[AvailableAction], Field(max_length=3, json_schema_extra={"uniqueItems": True})
    ]
    items: Annotated[list[ResidentPaymentOrderItem], Field(min_length=1)]
    expires_at: Timestamp
    paid_at: Timestamp | None
    closed_at: Timestamp | None
    created_at: Timestamp
    updated_at: Timestamp


class ResidentPaymentOrderPage(AdminSchema):
    items: Annotated[list[ResidentPaymentOrder], Field(max_length=100)]
    total: Annotated[int, Field(ge=0, le=9007199254740991)]
    page: Annotated[int, Field(ge=1, le=9007199254740991)]
    page_size: Annotated[int, Field(ge=1, le=100)]


class ResidentWechatPayClientParameters(AdminSchema):
    timeStamp: Annotated[str, Field(pattern=r"^[0-9]+$")]
    nonceStr: Annotated[str, Field(min_length=1, max_length=32)]
    package: Annotated[str, Field(pattern=r"^prepay_id=.+$")]
    signType: Literal["RSA"]
    paySign: Annotated[str, Field(min_length=1)]


class ResidentClientPaymentParameters(AdminSchema):
    payment_order_id: Identifier
    channel: Literal["wechat_pay"]
    client_parameters: ResidentWechatPayClientParameters
