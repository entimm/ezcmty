from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import WithJsonSchema
from sqlalchemy.orm import Session

from backend_app.api.client.dependencies import ResidentContext as Context
from backend_app.api.client.dependencies import client_responses
from backend_app.core.config import get_settings
from backend_app.core.openapi import get_request_id_headers
from backend_app.db.session import get_database_session
from backend_app.schemas.admin import Identifier
from backend_app.schemas.billing import Month
from backend_app.schemas.payments import resident_billing as schema
from backend_app.services.client.resident.billing import ResidentBillingService


def create_resident_billing_router() -> APIRouter:
    router = APIRouter(prefix="/v1/miniapp-users/me", tags=["payments"])

    def service(db: Annotated[Session, Depends(get_database_session)]) -> ResidentBillingService:
        return ResidentBillingService(db, get_settings())

    Service = Annotated[ResidentBillingService, Depends(service)]
    responses = client_responses()
    responses.pop(409)
    responses[200] = {
        "headers": {
            **get_request_id_headers(),
            "Cache-Control": {"schema": {"type": "string", "const": "no-store"}},
        }
    }

    @router.get(
        "/house-bindings/{binding_id}/bills",
        operation_id="listResidentHouseBills",
        response_model=schema.ResidentBillPage,
        responses=responses,
    )
    def bills(
        binding_id: Identifier,
        ctx: Context,
        svc: Service,
        scope: Literal["outstanding", "all"] = "outstanding",
        billing_month_from: Annotated[
            Month | None, WithJsonSchema({"type": "string", "pattern": r"^\d{4}-(0[1-9]|1[0-2])$"})
        ] = None,
        billing_month_to: Annotated[
            Month | None, WithJsonSchema({"type": "string", "pattern": r"^\d{4}-(0[1-9]|1[0-2])$"})
        ] = None,
        page: Annotated[int, Query(ge=1, le=9007199254740991)] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 20,
        sort: Literal["-billing_month,-id", "billing_month,id"] = "-billing_month,-id",
    ) -> schema.ResidentBillPage:
        return svc.list(
            ctx,
            binding_id,
            scope=scope,
            billing_month_from=billing_month_from,
            billing_month_to=billing_month_to,
            page=page,
            page_size=page_size,
            sort=sort,
        )

    @router.get(
        "/bills/{bill_id}",
        operation_id="getResidentBill",
        response_model=schema.ResidentBill,
        responses=responses,
    )
    def bill(bill_id: Identifier, ctx: Context, svc: Service) -> schema.ResidentBill:
        return svc.get(ctx, bill_id)

    @router.get(
        "/bills/{bill_id}/settlement-entries",
        operation_id="listResidentBillSettlementEntries",
        response_model=schema.ResidentBillSettlementEntryPage,
        responses=responses,
    )
    def entries(
        bill_id: Identifier,
        ctx: Context,
        svc: Service,
        page: Annotated[int, Query(ge=1, le=9007199254740991)] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 20,
        sort: Literal["-created_at,-id", "created_at,id"] = "-created_at,-id",
    ) -> schema.ResidentBillSettlementEntryPage:
        return svc.entries(ctx, bill_id, page=page, page_size=page_size, sort=sort)

    return router
