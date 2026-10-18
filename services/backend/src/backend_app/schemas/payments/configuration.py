from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field

from backend_app.schemas.admin import Identifier
from backend_app.schemas.payments.base import PaymentSchema

type PaymentConfigurationToken = Annotated[str, Field(min_length=1, max_length=256)]


class MerchantBindingCreate(PaymentSchema):
    merchant_no: Annotated[str, Field(min_length=1, max_length=64)]
    merchant_name: Annotated[str, Field(min_length=1, max_length=256)]
    expected_configuration_token: PaymentConfigurationToken


class MerchantBinding(PaymentSchema):
    id: Identifier
    property_company_id: Identifier
    service_provider_merchant_no: Annotated[str, Field(max_length=64)]
    merchant_no: Annotated[str, Field(max_length=64)]
    merchant_name: Annotated[str, Field(max_length=256)]
    enabled: bool
    max_ratio_bps: Annotated[int, Field(ge=0, le=10000, strict=True)] | None
    ratio_checked_at: datetime | None
    row_version: Annotated[int, Field(ge=1, le=9007199254740991, strict=True)]
    created_at: datetime
    updated_at: datetime


class ActiveMerchantBindingUpdate(PaymentSchema):
    binding_id: Identifier | None
    expected_configuration_token: PaymentConfigurationToken


class ProfitSharingRuleItemCreate(PaymentSchema):
    rate_bps: Annotated[int, Field(ge=0, le=10000, strict=True)]


class ProfitSharingRuleCreate(PaymentSchema):
    expected_configuration_token: PaymentConfigurationToken
    items: Annotated[list[ProfitSharingRuleItemCreate], Field(min_length=1, max_length=1)]


class ProfitSharingRuleItem(PaymentSchema):
    id: Identifier
    receiver_type: Literal["merchant"]
    receiver_account: Annotated[str, Field(max_length=128)]
    receiver_name: Annotated[str, Field(max_length=256)]
    relation_type: Literal["service_provider"]
    rate_bps: Annotated[int, Field(ge=0, le=10000, strict=True)]


class ProfitSharingRuleVersion(PaymentSchema):
    id: Identifier
    property_company_id: Identifier
    version_no: Annotated[int, Field(ge=1, le=9007199254740991, strict=True)]
    calculation_version: Literal[1]
    items: Annotated[list[ProfitSharingRuleItem], Field(min_length=1)]
    created_at: datetime


class PaymentConfiguration(PaymentSchema):
    property_company_id: Identifier
    configuration_token: PaymentConfigurationToken
    ready: bool
    reasons: Annotated[
        list[
            Literal[
                "company_disabled",
                "merchant_missing",
                "rule_missing",
                "merchant_unverified",
                "receiver_unready",
                "ratio_unknown",
                "ratio_exceeded",
                "channel_unavailable",
            ]
        ],
        Field(min_length=0),
    ]
    current_binding: MerchantBinding | None
    current_rule: ProfitSharingRuleVersion | None


class MerchantBindingPage(PaymentSchema):
    items: Annotated[list[MerchantBinding], Field(min_length=0)]
    total: Annotated[int, Field(ge=0, le=9007199254740991, strict=True)]
    page: Annotated[int, Field(ge=1, le=9007199254740991, strict=True)]
    page_size: Annotated[int, Field(ge=1, le=100, strict=True)]


class ProfitSharingRuleVersionPage(PaymentSchema):
    items: Annotated[list[ProfitSharingRuleVersion], Field(min_length=0)]
    total: Annotated[int, Field(ge=0, le=9007199254740991, strict=True)]
    page: Annotated[int, Field(ge=1, le=9007199254740991, strict=True)]
    page_size: Annotated[int, Field(ge=1, le=100, strict=True)]
