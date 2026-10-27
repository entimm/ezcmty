from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, Query, Response
from pydantic import WithJsonSchema
from sqlalchemy.orm import Session

from backend_app.api.client.dependencies import ResidentContext as Context
from backend_app.api.client.dependencies import client_responses
from backend_app.core.config import get_settings
from backend_app.db.session import get_database_session
from backend_app.schemas.admin import Identifier
from backend_app.schemas.miniapp import IdempotencyKey
from backend_app.schemas.payments import resident as schema
from backend_app.services.client.resident.payments import ResidentPaymentService


def service(db: Annotated[Session, Depends(get_database_session)]) -> ResidentPaymentService:
    return ResidentPaymentService(db, get_settings())


Service = Annotated[ResidentPaymentService, Depends(service)]
Page = Annotated[int, Query(ge=1, le=9007199254740991)]
PageSize = Annotated[int, Query(ge=1, le=100)]
Sort = Literal["-created_at,-id", "created_at,id"]
StatusFilter = Annotated[
    schema.PaymentStatus | None,
    WithJsonSchema(
        {
            "type": "string",
            "enum": ["pending", "unknown", "payable", "closing", "succeeded", "closed"],
        }
    ),
]
ConfirmationFilter = Annotated[
    schema.ConfirmationStatus | None,
    WithJsonSchema(
        {
            "type": "string",
            "enum": ["unconfirmed", "awaiting_posting", "posted"],
        }
    ),
]
KeyFilter = Annotated[
    IdempotencyKey | None,
    WithJsonSchema(
        {
            "type": "string",
            "minLength": 1,
            "maxLength": 128,
            "pattern": "^[A-Za-z0-9_-]{1,128}$",
        }
    ),
]
TimeFilter = Annotated[datetime | None, WithJsonSchema({"type": "string", "format": "date-time"})]


def responses(
    status: int = 200, *, conflict: bool = False, pending: bool = False
) -> dict[int | str, dict[str, Any]]:
    result: dict[int | str, dict[str, Any]] = client_responses(status)
    if not conflict:
        result.pop(409, None)
    result[status]["headers"]["Cache-Control"] = {"schema": {"type": "string", "const": "no-store"}}
    if pending:
        result[202] = {"headers": result[status]["headers"], "model": schema.ResidentPaymentOrder}
    return result


def create_resident_payment_router() -> APIRouter:
    router = APIRouter(prefix="/v1/miniapp-users/me/payment-orders", tags=["payments"])

    @router.get(
        "",
        operation_id="listResidentPaymentOrders",
        response_model=schema.ResidentPaymentOrderPage,
        responses=responses(),
    )
    def orders(
        ctx: Context,
        svc: Service,
        status: StatusFilter = None,
        confirmation_status: ConfirmationFilter = None,
        idempotency_key: KeyFilter = None,
        created_at_from: TimeFilter = None,
        created_at_to: TimeFilter = None,
        page: Page = 1,
        page_size: PageSize = 20,
        sort: Sort = "-created_at,-id",
    ) -> schema.ResidentPaymentOrderPage:
        return svc.list(
            ctx,
            status=status,
            confirmation_status=confirmation_status,
            idempotency_key=idempotency_key,
            created_at_from=created_at_from,
            created_at_to=created_at_to,
            page=page,
            page_size=page_size,
            sort=sort,
        )

    @router.post(
        "",
        operation_id="createResidentPaymentOrder",
        status_code=201,
        response_model=schema.ResidentPaymentOrder,
        responses=responses(201, conflict=True),
    )
    def create(
        data: schema.ResidentPaymentOrderCreate,
        ctx: Context,
        svc: Service,
        idempotency_key: Annotated[IdempotencyKey, Header(alias="Idempotency-Key")],
    ) -> schema.ResidentPaymentOrder:
        return svc.create(ctx, data, idempotency_key)

    @router.get(
        "/{payment_order_id}",
        operation_id="getResidentPaymentOrder",
        response_model=schema.ResidentPaymentOrder,
        responses=responses(),
    )
    def order(
        payment_order_id: Identifier, ctx: Context, svc: Service
    ) -> schema.ResidentPaymentOrder:
        return svc.get(ctx, payment_order_id)

    @router.post(
        "/{payment_order_id}/client-payment-parameters",
        operation_id="createResidentClientPaymentParameters",
        response_model=schema.ResidentClientPaymentParameters,
        responses=responses(conflict=True),
    )
    def parameters(
        payment_order_id: Identifier, ctx: Context, svc: Service
    ) -> schema.ResidentClientPaymentParameters:
        return svc.parameters(ctx, payment_order_id)

    @router.post(
        "/{payment_order_id}/refreshes",
        operation_id="createResidentPaymentRefresh",
        response_model=schema.ResidentPaymentOrder,
        responses=responses(pending=True),
    )
    def refresh(
        payment_order_id: Identifier, ctx: Context, svc: Service, response: Response
    ) -> schema.ResidentPaymentOrder:
        result, pending = svc.request_recovery(ctx, payment_order_id)
        response.status_code = 202 if pending else 200
        return result

    @router.post(
        "/{payment_order_id}/closures",
        operation_id="createResidentPaymentClosure",
        response_model=schema.ResidentPaymentOrder,
        responses=responses(pending=True),
    )
    def close(
        payment_order_id: Identifier, ctx: Context, svc: Service, response: Response
    ) -> schema.ResidentPaymentOrder:
        result, pending = svc.request_recovery(ctx, payment_order_id, close=True)
        response.status_code = 202 if pending else 200
        return result

    return router
