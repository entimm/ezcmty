from collections.abc import Callable
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.params import Depends as DependsParameter
from pydantic import AwareDatetime, WithJsonSchema
from sqlalchemy.orm import Session

from backend_app.api.payment_headers import no_store
from backend_app.core.config import get_settings
from backend_app.core.identifiers import UUID_PATTERN
from backend_app.core.openapi import get_problem_responses, get_request_id_headers
from backend_app.db.session import get_database_session
from backend_app.schemas.admin import Identifier
from backend_app.schemas.payments import management as schema
from backend_app.services.contracts.admin import AdminContext
from backend_app.services.platform_admin.payments import PlatformPaymentService
from backend_app.services.property_admin.payments import PropertyPaymentService


def create_payment_management_router(
    scope: Literal["platform_admin", "property_admin"],
    permission: Callable[[str], DependsParameter],
) -> APIRouter:
    router = APIRouter(tags=["payment-management"], dependencies=[Depends(no_store)])
    prefix = "platform" if scope == "platform_admin" else "property"
    errors = get_problem_responses(401, 403, 404, 409, 422, 500, 503)
    ok = {
        **errors,
        200: {
            "headers": {
                **get_request_id_headers(),
                "Cache-Control": {"schema": {"type": "string", "const": "no-store"}},
            }
        },
    }

    def service(
        db: Annotated[Session, Depends(get_database_session)],
    ) -> PlatformPaymentService | PropertyPaymentService:
        if scope == "platform_admin":
            return PlatformPaymentService(db, get_settings())
        return PropertyPaymentService(db, get_settings())

    Service = Annotated[PlatformPaymentService | PropertyPaymentService, Depends(service)]

    @router.get(
        "/v1/payment-orders",
        operation_id="listManagedPaymentOrders",
        response_model=schema.ManagedPaymentOrderPage,
        responses=ok,
    )
    def payments(
        svc: Service,
        ctx: Annotated[AdminContext, permission(prefix + ".payment.read")],
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 20,
        sort: Annotated[Literal["created_at,id", "-created_at,-id"], Query()] = "-created_at,-id",
        property_company_id: Annotated[
            Identifier | None,
            Query(),
            WithJsonSchema(
                {
                    "type": "string",
                    "format": "uuid",
                    "minLength": 36,
                    "maxLength": 36,
                    "pattern": UUID_PATTERN,
                    "description": "带连字符的 UUIDv4 或 UUIDv7；响应统一使用小写标准形式。",
                }
            ),
        ] = None,
        community_id: Annotated[
            Identifier | None,
            Query(),
            WithJsonSchema(
                {
                    "type": "string",
                    "format": "uuid",
                    "minLength": 36,
                    "maxLength": 36,
                    "pattern": UUID_PATTERN,
                    "description": "带连字符的 UUIDv4 或 UUIDv7；响应统一使用小写标准形式。",
                }
            ),
        ] = None,
        status: Annotated[
            Literal["pending", "unknown", "payable", "closing", "succeeded", "closed"] | None,
            Query(),
            WithJsonSchema(
                {
                    "type": "string",
                    "enum": ["pending", "unknown", "payable", "closing", "succeeded", "closed"],
                }
            ),
        ] = None,
        order_no: Annotated[
            str | None,
            Query(min_length=1, max_length=64),
            WithJsonSchema({"type": "string", "minLength": 1, "maxLength": 64}),
        ] = None,
        created_from: Annotated[
            AwareDatetime | None, Query(), WithJsonSchema({"type": "string", "format": "date-time"})
        ] = None,
        created_before: Annotated[
            AwareDatetime | None, Query(), WithJsonSchema({"type": "string", "format": "date-time"})
        ] = None,
        house_id: Annotated[
            Identifier | None,
            Query(),
            WithJsonSchema(
                {
                    "type": "string",
                    "format": "uuid",
                    "minLength": 36,
                    "maxLength": 36,
                    "pattern": UUID_PATTERN,
                    "description": "带连字符的 UUIDv4 或 UUIDv7；响应统一使用小写标准形式。",
                }
            ),
        ] = None,
        channel_transaction_no: Annotated[
            str | None,
            Query(min_length=1, max_length=64),
            WithJsonSchema({"type": "string", "minLength": 1, "maxLength": 64}),
        ] = None,
        confirmation_status: Annotated[
            Literal["unconfirmed", "awaiting_posting", "posted"] | None,
            Query(),
            WithJsonSchema(
                {"type": "string", "enum": ["unconfirmed", "awaiting_posting", "posted"]}
            ),
        ] = None,
    ) -> schema.ManagedPaymentOrderPage:
        return svc.payments(
            ctx,
            page=page,
            page_size=page_size,
            sort=sort,
            property_company_id=property_company_id,
            community_id=community_id,
            status=status,
            order_no=order_no,
            created_from=created_from,
            created_before=created_before,
            house_id=house_id,
            channel_transaction_no=channel_transaction_no,
            confirmation_status=confirmation_status,
        )

    @router.get(
        "/v1/payment-orders/{payment_order_id}",
        operation_id="getManagedPaymentOrder",
        response_model=schema.ManagedPaymentOrder,
        responses=ok,
    )
    def payment(
        payment_order_id: Identifier,
        svc: Service,
        ctx: Annotated[AdminContext, permission(prefix + ".payment.read")],
    ) -> schema.ManagedPaymentOrder:
        return svc.payment(ctx, payment_order_id)

    @router.get(
        "/v1/profit-sharing-orders",
        operation_id="listManagedProfitSharingOrders",
        response_model=schema.ManagedProfitSharingOrderPage,
        responses=ok,
    )
    def sharings(
        svc: Service,
        ctx: Annotated[AdminContext, permission(prefix + ".payment_funds.read")],
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 20,
        sort: Annotated[Literal["created_at,id", "-created_at,-id"], Query()] = "-created_at,-id",
        property_company_id: Annotated[
            Identifier | None,
            Query(),
            WithJsonSchema(
                {
                    "type": "string",
                    "format": "uuid",
                    "minLength": 36,
                    "maxLength": 36,
                    "pattern": UUID_PATTERN,
                    "description": "带连字符的 UUIDv4 或 UUIDv7；响应统一使用小写标准形式。",
                }
            ),
        ] = None,
        community_id: Annotated[
            Identifier | None,
            Query(),
            WithJsonSchema(
                {
                    "type": "string",
                    "format": "uuid",
                    "minLength": 36,
                    "maxLength": 36,
                    "pattern": UUID_PATTERN,
                    "description": "带连字符的 UUIDv4 或 UUIDv7；响应统一使用小写标准形式。",
                }
            ),
        ] = None,
        status: Annotated[
            Literal["pending", "unknown", "processing", "finished", "rejected"] | None,
            Query(),
            WithJsonSchema(
                {
                    "type": "string",
                    "enum": ["pending", "unknown", "processing", "finished", "rejected"],
                }
            ),
        ] = None,
        order_no: Annotated[
            str | None,
            Query(min_length=1, max_length=64),
            WithJsonSchema({"type": "string", "minLength": 1, "maxLength": 64}),
        ] = None,
        created_from: Annotated[
            AwareDatetime | None, Query(), WithJsonSchema({"type": "string", "format": "date-time"})
        ] = None,
        created_before: Annotated[
            AwareDatetime | None, Query(), WithJsonSchema({"type": "string", "format": "date-time"})
        ] = None,
        payment_order_id: Annotated[
            Identifier | None,
            Query(),
            WithJsonSchema(
                {
                    "type": "string",
                    "format": "uuid",
                    "minLength": 36,
                    "maxLength": 36,
                    "pattern": UUID_PATTERN,
                    "description": "带连字符的 UUIDv4 或 UUIDv7；响应统一使用小写标准形式。",
                }
            ),
        ] = None,
    ) -> schema.ManagedProfitSharingOrderPage:
        return svc.sharings(
            ctx,
            page=page,
            page_size=page_size,
            sort=sort,
            property_company_id=property_company_id,
            community_id=community_id,
            status=status,
            order_no=order_no,
            created_from=created_from,
            created_before=created_before,
            payment_order_id=payment_order_id,
        )

    @router.get(
        "/v1/profit-sharing-orders/{profit_sharing_order_id}",
        operation_id="getManagedProfitSharingOrder",
        response_model=schema.ManagedProfitSharingOrder,
        responses=ok,
    )
    def sharing(
        profit_sharing_order_id: Identifier,
        svc: Service,
        ctx: Annotated[AdminContext, permission(prefix + ".payment_funds.read")],
    ) -> schema.ManagedProfitSharingOrder:
        return svc.sharing(ctx, profit_sharing_order_id)

    @router.get(
        "/v1/payment-unfreeze-orders",
        operation_id="listManagedUnfreezeOrders",
        response_model=schema.ManagedUnfreezeOrderPage,
        responses=ok,
    )
    def unfreezes(
        svc: Service,
        ctx: Annotated[AdminContext, permission(prefix + ".payment_funds.read")],
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 20,
        sort: Annotated[Literal["created_at,id", "-created_at,-id"], Query()] = "-created_at,-id",
        property_company_id: Annotated[
            Identifier | None,
            Query(),
            WithJsonSchema(
                {
                    "type": "string",
                    "format": "uuid",
                    "minLength": 36,
                    "maxLength": 36,
                    "pattern": UUID_PATTERN,
                    "description": "带连字符的 UUIDv4 或 UUIDv7；响应统一使用小写标准形式。",
                }
            ),
        ] = None,
        community_id: Annotated[
            Identifier | None,
            Query(),
            WithJsonSchema(
                {
                    "type": "string",
                    "format": "uuid",
                    "minLength": 36,
                    "maxLength": 36,
                    "pattern": UUID_PATTERN,
                    "description": "带连字符的 UUIDv4 或 UUIDv7；响应统一使用小写标准形式。",
                }
            ),
        ] = None,
        status: Annotated[
            Literal["pending", "unknown", "processing", "succeeded", "failed", "no_remaining"]
            | None,
            Query(),
            WithJsonSchema(
                {
                    "type": "string",
                    "enum": [
                        "pending",
                        "unknown",
                        "processing",
                        "succeeded",
                        "failed",
                        "no_remaining",
                    ],
                }
            ),
        ] = None,
        order_no: Annotated[
            str | None,
            Query(min_length=1, max_length=64),
            WithJsonSchema({"type": "string", "minLength": 1, "maxLength": 64}),
        ] = None,
        created_from: Annotated[
            AwareDatetime | None, Query(), WithJsonSchema({"type": "string", "format": "date-time"})
        ] = None,
        created_before: Annotated[
            AwareDatetime | None, Query(), WithJsonSchema({"type": "string", "format": "date-time"})
        ] = None,
        payment_order_id: Annotated[
            Identifier | None,
            Query(),
            WithJsonSchema(
                {
                    "type": "string",
                    "format": "uuid",
                    "minLength": 36,
                    "maxLength": 36,
                    "pattern": UUID_PATTERN,
                    "description": "带连字符的 UUIDv4 或 UUIDv7；响应统一使用小写标准形式。",
                }
            ),
        ] = None,
    ) -> schema.ManagedUnfreezeOrderPage:
        return svc.unfreezes(
            ctx,
            page=page,
            page_size=page_size,
            sort=sort,
            property_company_id=property_company_id,
            community_id=community_id,
            status=status,
            order_no=order_no,
            created_from=created_from,
            created_before=created_before,
            payment_order_id=payment_order_id,
        )

    @router.get(
        "/v1/payment-unfreeze-orders/{unfreeze_order_id}",
        operation_id="getManagedUnfreezeOrder",
        response_model=schema.ManagedUnfreezeOrder,
        responses=ok,
    )
    def unfreeze(
        unfreeze_order_id: Identifier,
        svc: Service,
        ctx: Annotated[AdminContext, permission(prefix + ".payment_funds.read")],
    ) -> schema.ManagedUnfreezeOrder:
        return svc.unfreeze(ctx, unfreeze_order_id)

    @router.get(
        "/v1/payment-reconciliation-runs",
        operation_id="listManagedReconciliationRuns",
        response_model=schema.ManagedReconciliationRunPage,
        responses=ok,
    )
    def runs(
        svc: Service,
        ctx: Annotated[AdminContext, permission(prefix + ".payment_reconciliation.read")],
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 20,
        sort: Annotated[Literal["created_at,id", "-created_at,-id"], Query()] = "-created_at,-id",
        property_company_id: Annotated[
            Identifier | None,
            Query(),
            WithJsonSchema(
                {
                    "type": "string",
                    "format": "uuid",
                    "minLength": 36,
                    "maxLength": 36,
                    "pattern": UUID_PATTERN,
                    "description": "带连字符的 UUIDv4 或 UUIDv7；响应统一使用小写标准形式。",
                }
            ),
        ] = None,
        business_date_from: Annotated[
            date | None, Query(), WithJsonSchema({"type": "string", "format": "date"})
        ] = None,
        business_date_through: Annotated[
            date | None, Query(), WithJsonSchema({"type": "string", "format": "date"})
        ] = None,
        statement_type: Annotated[
            Literal["trade", "profit_sharing", "platform_fundflow"] | None,
            Query(),
            WithJsonSchema(
                {"type": "string", "enum": ["trade", "profit_sharing", "platform_fundflow"]}
            ),
        ] = None,
        status: Annotated[
            Literal["ready", "running", "completed", "failed"] | None,
            Query(),
            WithJsonSchema({"type": "string", "enum": ["ready", "running", "completed", "failed"]}),
        ] = None,
    ) -> schema.ManagedReconciliationRunPage:
        return svc.runs(
            ctx,
            page=page,
            page_size=page_size,
            sort=sort,
            property_company_id=property_company_id,
            business_date_from=business_date_from,
            business_date_through=business_date_through,
            statement_type=statement_type,
            status=status,
        )

    @router.get(
        "/v1/payment-reconciliation-runs/{reconciliation_run_id}",
        operation_id="getManagedReconciliationRun",
        response_model=schema.ManagedReconciliationRun,
        responses=ok,
    )
    def run(
        reconciliation_run_id: Identifier,
        svc: Service,
        ctx: Annotated[AdminContext, permission(prefix + ".payment_reconciliation.read")],
    ) -> schema.ManagedReconciliationRun:
        return svc.run(ctx, reconciliation_run_id)

    @router.get(
        "/v1/payment-reconciliation-discrepancies",
        operation_id="listManagedReconciliationDiscrepancies",
        response_model=schema.ManagedReconciliationDiscrepancyPage,
        responses=ok,
    )
    def discrepancies(
        svc: Service,
        ctx: Annotated[AdminContext, permission(prefix + ".payment_reconciliation.read")],
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 20,
        sort: Annotated[Literal["created_at,id", "-created_at,-id"], Query()] = "-created_at,-id",
        property_company_id: Annotated[
            Identifier | None,
            Query(),
            WithJsonSchema(
                {
                    "type": "string",
                    "format": "uuid",
                    "minLength": 36,
                    "maxLength": 36,
                    "pattern": UUID_PATTERN,
                    "description": "带连字符的 UUIDv4 或 UUIDv7；响应统一使用小写标准形式。",
                }
            ),
        ] = None,
        business_date_from: Annotated[
            date | None, Query(), WithJsonSchema({"type": "string", "format": "date"})
        ] = None,
        business_date_through: Annotated[
            date | None, Query(), WithJsonSchema({"type": "string", "format": "date"})
        ] = None,
        statement_type: Annotated[
            Literal["trade", "profit_sharing", "platform_fundflow"] | None,
            Query(),
            WithJsonSchema(
                {"type": "string", "enum": ["trade", "profit_sharing", "platform_fundflow"]}
            ),
        ] = None,
        reconciliation_run_id: Annotated[
            Identifier | None,
            Query(),
            WithJsonSchema(
                {
                    "type": "string",
                    "format": "uuid",
                    "minLength": 36,
                    "maxLength": 36,
                    "pattern": UUID_PATTERN,
                    "description": "带连字符的 UUIDv4 或 UUIDv7；响应统一使用小写标准形式。",
                }
            ),
        ] = None,
        payment_order_id: Annotated[
            Identifier | None,
            Query(),
            WithJsonSchema(
                {
                    "type": "string",
                    "format": "uuid",
                    "minLength": 36,
                    "maxLength": 36,
                    "pattern": UUID_PATTERN,
                    "description": "带连字符的 UUIDv4 或 UUIDv7；响应统一使用小写标准形式。",
                }
            ),
        ] = None,
        status: Annotated[
            Literal["open", "observing", "resolved"] | None,
            Query(),
            WithJsonSchema({"type": "string", "enum": ["open", "observing", "resolved"]}),
        ] = None,
        difference_type: Annotated[
            Literal[
                "channel_only", "local_only", "amount_mismatch", "status_mismatch", "unclassified"
            ]
            | None,
            Query(),
            WithJsonSchema(
                {
                    "type": "string",
                    "enum": [
                        "channel_only",
                        "local_only",
                        "amount_mismatch",
                        "status_mismatch",
                        "unclassified",
                    ],
                }
            ),
        ] = None,
    ) -> schema.ManagedReconciliationDiscrepancyPage:
        return svc.discrepancies(
            ctx,
            page=page,
            page_size=page_size,
            sort=sort,
            property_company_id=property_company_id,
            business_date_from=business_date_from,
            business_date_through=business_date_through,
            statement_type=statement_type,
            reconciliation_run_id=reconciliation_run_id,
            payment_order_id=payment_order_id,
            status=status,
            difference_type=difference_type,
        )

    @router.get(
        "/v1/payment-reconciliation-discrepancies/{discrepancy_id}",
        operation_id="getManagedReconciliationDiscrepancy",
        response_model=schema.ManagedReconciliationDiscrepancy,
        responses=ok,
    )
    def discrepancy(
        discrepancy_id: Identifier,
        svc: Service,
        ctx: Annotated[AdminContext, permission(prefix + ".payment_reconciliation.read")],
    ) -> schema.ManagedReconciliationDiscrepancy:
        return svc.discrepancy(ctx, discrepancy_id)

    return router
