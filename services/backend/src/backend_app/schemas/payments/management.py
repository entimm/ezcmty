from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import Field

from backend_app.schemas.admin import Identifier
from backend_app.schemas.payments.base import PaymentSchema


class ManagedPaymentItem(PaymentSchema):
    id: Identifier
    bill_id: Identifier
    community_id: Identifier
    house_id: Identifier
    house_label: Annotated[str, Field(max_length=512)]
    billing_month: Annotated[str, Field(pattern="^\\d{4}-(0[1-9]|1[0-2])$")]
    amount_cents: Annotated[int, Field(ge=1, le=9007199254740991, strict=True)]


type PaymentStateToken = Annotated[str, Field(min_length=1, max_length=256)]


class ManagedPaymentOrder(PaymentSchema):
    id: Identifier
    property_company_id: Identifier
    order_no: Annotated[str, Field(max_length=64)]
    channel_transaction_no: Annotated[str, Field(max_length=64)] | None
    merchant_binding_id: Identifier
    rule_version_id: Identifier
    merchant_name: Annotated[str, Field(max_length=256)]
    merchant_no: Annotated[str, Field(max_length=64)]
    amount_cents: Annotated[int, Field(ge=1, le=9007199254740991, strict=True)]
    payer_total_cents: Annotated[int, Field(ge=0, le=9007199254740991, strict=True)] | None
    status: Literal["pending", "unknown", "payable", "closing", "succeeded", "closed"]
    confirmation_status: Literal["unconfirmed", "awaiting_posting", "posted"]
    items: Annotated[list[ManagedPaymentItem], Field(min_length=1)]
    expires_at: datetime
    paid_at: datetime | None
    closed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    state_token: PaymentStateToken


class ManagedPaymentOrderPage(PaymentSchema):
    items: Annotated[list[ManagedPaymentOrder], Field(min_length=0)]
    total: Annotated[int, Field(ge=0, le=9007199254740991, strict=True)]
    page: Annotated[int, Field(ge=1, le=9007199254740991, strict=True)]
    page_size: Annotated[int, Field(ge=1, le=100, strict=True)]


class ManagedProfitSharingItem(PaymentSchema):
    id: Identifier
    allocation_id: Identifier
    receiver_type: Literal["merchant"]
    receiver_account: Annotated[str, Field(max_length=128)]
    receiver_name: Annotated[str, Field(max_length=256)]
    allocation_cents: Annotated[int, Field(ge=1, le=9007199254740991, strict=True)]
    amount_cents: Annotated[int, Field(ge=1, le=9007199254740991, strict=True)]
    result: Literal["success", "failed"] | None
    channel_detail_no: Annotated[str, Field(max_length=64)] | None
    failure_summary: Annotated[str, Field(max_length=1000)] | None
    finished_at: datetime | None


class ManagedProfitSharingOrder(PaymentSchema):
    id: Identifier
    property_company_id: Identifier
    payment_order_id: Identifier
    order_no: Annotated[str, Field(max_length=64)]
    channel_order_no: Annotated[str, Field(max_length=64)] | None
    status: Literal["pending", "unknown", "processing", "finished", "rejected"]
    items: Annotated[list[ManagedProfitSharingItem], Field(min_length=1)]
    created_at: datetime
    updated_at: datetime


class ManagedProfitSharingOrderPage(PaymentSchema):
    items: Annotated[list[ManagedProfitSharingOrder], Field(min_length=0)]
    total: Annotated[int, Field(ge=0, le=9007199254740991, strict=True)]
    page: Annotated[int, Field(ge=1, le=9007199254740991, strict=True)]
    page_size: Annotated[int, Field(ge=1, le=100, strict=True)]


class ManagedUnfreezeOrder(PaymentSchema):
    id: Identifier
    property_company_id: Identifier
    payment_order_id: Identifier
    order_no: Annotated[str, Field(max_length=64)]
    channel_order_no: Annotated[str, Field(max_length=64)] | None
    status: Literal["pending", "unknown", "processing", "succeeded", "failed", "no_remaining"]
    unfrozen_cents: Annotated[int, Field(ge=0, le=9007199254740991, strict=True)] | None
    channel_detail_no: Annotated[str, Field(max_length=64)] | None
    failure_summary: Annotated[str, Field(max_length=1000)] | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ManagedUnfreezeOrderPage(PaymentSchema):
    items: Annotated[list[ManagedUnfreezeOrder], Field(min_length=0)]
    total: Annotated[int, Field(ge=0, le=9007199254740991, strict=True)]
    page: Annotated[int, Field(ge=1, le=9007199254740991, strict=True)]
    page_size: Annotated[int, Field(ge=1, le=100, strict=True)]


class ReconciliationSummary(PaymentSchema):
    local_count: Annotated[int, Field(ge=0, le=9007199254740991, strict=True)]
    channel_count: Annotated[int, Field(ge=0, le=9007199254740991, strict=True)]
    matched_count: Annotated[int, Field(ge=0, le=9007199254740991, strict=True)]
    discrepancy_count: Annotated[int, Field(ge=0, le=9007199254740991, strict=True)]
    local_amount_cents: (
        Annotated[int, Field(ge=-9007199254740991, le=9007199254740991, strict=True)] | None
    )
    channel_amount_cents: (
        Annotated[int, Field(ge=-9007199254740991, le=9007199254740991, strict=True)] | None
    )
    channel_fee_cents: Annotated[int, Field(ge=0, le=9007199254740991, strict=True)] | None


class ManagedReconciliationRun(PaymentSchema):
    id: Identifier
    business_date: date
    statement_type: Literal["trade", "profit_sharing", "platform_fundflow"]
    service_provider_merchant_no: Annotated[str, Field(max_length=64)]
    merchant_no: Annotated[str, Field(max_length=64)] | None
    status: Literal["ready", "running", "completed", "failed"]
    projection: Literal["batch", "company"]
    property_company_id: Identifier | None
    source_digest: Annotated[str, Field(max_length=128)] | None
    summary: ReconciliationSummary
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None
    state_token: PaymentStateToken


class ManagedReconciliationRunPage(PaymentSchema):
    items: Annotated[list[ManagedReconciliationRun], Field(min_length=0)]
    total: Annotated[int, Field(ge=0, le=9007199254740991, strict=True)]
    page: Annotated[int, Field(ge=1, le=9007199254740991, strict=True)]
    page_size: Annotated[int, Field(ge=1, le=100, strict=True)]


type ReconciliationCheckCode = Literal[
    "business_identity",
    "payment_amount",
    "payment_status",
    "bill_posting",
    "profit_sharing_amount",
    "profit_sharing_status",
    "unfreeze_amount",
    "unfreeze_status",
    "channel_fee",
    "platform_fundflow_amount",
    "unclassified",
]


class ReconciliationEvidence(PaymentSchema):
    source: Literal[
        "channel_trade",
        "channel_profit_sharing",
        "channel_fundflow",
        "order_query",
        "unfreeze_query",
        "internal",
    ]
    check_code: ReconciliationCheckCode
    source_digest: Annotated[str, Field(max_length=128)] | None
    source_request_id: Identifier | None
    order_no: Annotated[str, Field(max_length=64)] | None
    channel_transaction_no: Annotated[str, Field(max_length=64)] | None
    channel_order_no: Annotated[str, Field(max_length=64)] | None
    channel_detail_no: Annotated[str, Field(max_length=64)] | None
    statement_line_no: Annotated[int, Field(ge=1, le=9007199254740991, strict=True)] | None
    expected_status: Annotated[str, Field(max_length=32)] | None
    actual_status: Annotated[str, Field(max_length=32)] | None
    checked_at: datetime


class ManagedReconciliationDiscrepancy(PaymentSchema):
    id: Identifier
    reconciliation_run_id: Identifier
    property_company_id: Identifier | None
    difference_type: Literal[
        "channel_only", "local_only", "amount_mismatch", "status_mismatch", "unclassified"
    ]
    reference_key: Annotated[str, Field(max_length=256)]
    payment_order_id: Identifier | None
    profit_sharing_order_item_id: Identifier | None
    expected_cents: (
        Annotated[int, Field(ge=-9007199254740991, le=9007199254740991, strict=True)] | None
    )
    actual_cents: (
        Annotated[int, Field(ge=-9007199254740991, le=9007199254740991, strict=True)] | None
    )
    evidence: ReconciliationEvidence
    status: Literal["open", "observing", "resolved"]
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None
    resolved_by: Identifier | None
    resolution_note: Annotated[str, Field(max_length=1000)] | None
    state_token: PaymentStateToken


class ManagedReconciliationDiscrepancyPage(PaymentSchema):
    items: Annotated[list[ManagedReconciliationDiscrepancy], Field(min_length=0)]
    total: Annotated[int, Field(ge=0, le=9007199254740991, strict=True)]
    page: Annotated[int, Field(ge=1, le=9007199254740991, strict=True)]
    page_size: Annotated[int, Field(ge=1, le=100, strict=True)]


class PaymentRecoveryRequest(PaymentSchema):
    reason: Annotated[str, Field(min_length=1, max_length=1000, pattern="\\S")]
    expected_state_token: PaymentStateToken


class PaymentRecoveryAccepted(PaymentSchema):
    target_type: Literal["payment_order", "reconciliation_run", "reconciliation_discrepancy"]
    target_id: Identifier
    accepted_at: datetime


class ReconciliationExternalResolutionRequest(PaymentSchema):
    reason: Annotated[str, Field(min_length=1, max_length=1000, pattern="\\S")]
    evidence_reference: Annotated[str, Field(min_length=1, max_length=256, pattern="\\S")]
    expected_state_token: PaymentStateToken
