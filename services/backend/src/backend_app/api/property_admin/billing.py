from collections.abc import Callable
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.params import Depends as DependsParameter
from sqlalchemy.orm import Session

from backend_app.core.openapi import get_problem_responses, get_request_id_headers
from backend_app.db.session import get_database_session
from backend_app.schemas import billing as schema
from backend_app.schemas.admin import Identifier
from backend_app.services.contracts.admin import AdminContext
from backend_app.services.property_admin.billing import PropertyBillingService


def create_property_billing_router(
    permission: Callable[[str], DependsParameter], check_write: Callable[..., None]
) -> APIRouter:
    router = APIRouter(tags=["billing"])
    errors = get_problem_responses(401, 403, 404, 409, 422, 500, 503)
    ok = {**errors, 200: {"headers": get_request_id_headers()}}
    created = {**errors, 201: {"headers": get_request_id_headers()}}

    def service(db: Annotated[Session, Depends(get_database_session)]) -> PropertyBillingService:
        return PropertyBillingService(db)

    Service = Annotated[PropertyBillingService, Depends(service)]
    Key = Annotated[schema.IdempotencyKey, Header(alias="Idempotency-Key")]

    @router.get(
        "/v1/communities/{community_id}/houses/{house_id}/property-fee-basis-versions",
        response_model=schema.FeeBasisPage,
        operation_id="listFeeBasisVersions",
        responses=ok,
    )
    def list_bases(
        community_id: Identifier,
        house_id: Identifier,
        svc: Service,
        ctx: Annotated[AdminContext, permission("property.bill.read")],
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    ) -> schema.FeeBasisPage:
        return svc.list_bases(ctx, community_id, house_id, page=page, page_size=page_size)

    @router.post(
        "/v1/communities/{community_id}/houses/{house_id}/property-fee-basis-versions",
        response_model=schema.FeeBasisVersion,
        operation_id="createFeeBasisVersion",
        responses=created,
        status_code=201,
        dependencies=[Depends(check_write)],
    )
    def create_basis(
        community_id: Identifier,
        house_id: Identifier,
        data: schema.FeeBasisCreate,
        request: Request,
        svc: Service,
        ctx: Annotated[AdminContext, permission("property.fee_basis.manage")],
    ) -> schema.FeeBasisVersion:
        return svc.create_basis(ctx, community_id, house_id, data, request.state.request_id)

    @router.get(
        "/v1/communities/{community_id}/houses/{house_id}/property-fee-basis-versions/{version_id}",
        response_model=schema.FeeBasisVersion,
        operation_id="getFeeBasisVersion",
        responses=ok,
    )
    def get_basis(
        community_id: Identifier,
        house_id: Identifier,
        version_id: Identifier,
        svc: Service,
        ctx: Annotated[AdminContext, permission("property.bill.read")],
    ) -> schema.FeeBasisVersion:
        return svc.get_basis(ctx, community_id, house_id, version_id)

    @router.post(
        "/v1/communities/{community_id}/houses/{house_id}/property-fee-calculations",
        response_model=schema.FeeCalculation,
        operation_id="calculatePropertyFee",
        responses=ok,
        dependencies=[Depends(check_write)],
    )
    def calculate(
        community_id: Identifier,
        house_id: Identifier,
        data: schema.FeeCalculationRequest,
        svc: Service,
        ctx: Annotated[AdminContext, permission("property.bill.read")],
    ) -> schema.FeeCalculation:
        return svc.calculate(ctx, community_id, house_id, data)

    @router.get(
        "/v1/communities/{community_id}/bills",
        response_model=schema.BillPage,
        operation_id="listBills",
        responses=ok,
    )
    def list_bills(
        community_id: Identifier,
        svc: Service,
        ctx: Annotated[AdminContext, permission("property.bill.read")],
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 20,
        house_id: Identifier | None = None,
        space_node_id: Identifier | None = None,
        billing_month_from: Annotated[schema.Month | None, Query()] = None,
        billing_month_to: Annotated[schema.Month | None, Query()] = None,
        lifecycle_status: Literal["active", "voided"] = "active",
        settlement_status: Literal["unpaid", "partially_settled", "settled"] | None = None,
        outstanding_only: bool = False,
        external_bill_no: Annotated[str | None, Query(max_length=128)] = None,
        due_date_from: date | None = None,
        due_date_to: date | None = None,
        is_overdue: bool | None = None,
        sort: Literal[
            "-period_start",
            "period_start",
            "-created_at",
            "created_at",
            "due_date",
            "-due_date",
            "receivable_cents",
            "-receivable_cents",
            "outstanding_cents",
            "-outstanding_cents",
        ] = "-period_start",
    ) -> schema.BillPage:
        return svc.list_bills(
            ctx,
            community_id,
            house_id=house_id,
            space_node_id=space_node_id,
            billing_month_from=billing_month_from,
            billing_month_to=billing_month_to,
            lifecycle_status=lifecycle_status,
            settlement_status=settlement_status,
            outstanding_only=outstanding_only,
            external_bill_no=external_bill_no,
            due_date_from=due_date_from,
            due_date_to=due_date_to,
            is_overdue=is_overdue,
            sort=sort,
            page=page,
            page_size=page_size,
        )

    @router.get(
        "/v1/communities/{community_id}/bills/{bill_id}",
        response_model=schema.Bill,
        operation_id="getBill",
        responses=ok,
    )
    def get_bill(
        community_id: Identifier,
        bill_id: Identifier,
        svc: Service,
        ctx: Annotated[AdminContext, permission("property.bill.read")],
    ) -> schema.Bill:
        return svc.get_bill(ctx, community_id, bill_id)

    @router.post(
        "/v1/communities/{community_id}/bills",
        response_model=schema.BillWriteResult,
        operation_id="createBill",
        responses=created,
        status_code=201,
        dependencies=[Depends(check_write)],
    )
    def create_bill(
        community_id: Identifier,
        data: schema.BillCreate,
        request: Request,
        key: Key,
        svc: Service,
        ctx: Annotated[AdminContext, permission("property.bill.manage")],
    ) -> schema.BillWriteResult:
        return svc.write(ctx, community_id, "create", data, key, request.state.request_id)

    @router.patch(
        "/v1/communities/{community_id}/bills/{bill_id}",
        response_model=schema.BillWriteResult,
        operation_id="updateBill",
        responses=ok,
        dependencies=[Depends(check_write)],
    )
    def update_bill(
        community_id: Identifier,
        bill_id: Identifier,
        data: schema.BillUpdate,
        request: Request,
        key: Key,
        svc: Service,
        ctx: Annotated[AdminContext, permission("property.bill.manage")],
    ) -> schema.BillWriteResult:
        return svc.write(
            ctx, community_id, "update", data, key, request.state.request_id, bill_id=bill_id
        )

    @router.post(
        "/v1/communities/{community_id}/bills/{bill_id}/voids",
        response_model=schema.BillWriteResult,
        operation_id="voidBill",
        responses=ok,
        dependencies=[Depends(check_write)],
    )
    def void_bill(
        community_id: Identifier,
        bill_id: Identifier,
        data: schema.BillReasonAction,
        request: Request,
        key: Key,
        svc: Service,
        ctx: Annotated[AdminContext, permission("property.bill.void")],
    ) -> schema.BillWriteResult:
        return svc.write(
            ctx, community_id, "void", data, key, request.state.request_id, bill_id=bill_id
        )

    @router.post(
        "/v1/communities/{community_id}/bills/{bill_id}/offline-receipts",
        response_model=schema.BillWriteResult,
        operation_id="createOfflineReceipt",
        responses=created,
        status_code=201,
        dependencies=[Depends(check_write)],
    )
    def create_receipt(
        community_id: Identifier,
        bill_id: Identifier,
        data: schema.ReceiptCreate,
        request: Request,
        key: Key,
        svc: Service,
        ctx: Annotated[AdminContext, permission("property.bill_receipt.create")],
    ) -> schema.BillWriteResult:
        return svc.write(
            ctx, community_id, "receipt", data, key, request.state.request_id, bill_id=bill_id
        )

    @router.post(
        "/v1/communities/{community_id}/bills/{bill_id}/offline-receipts/{entry_id}/corrections",
        response_model=schema.BillWriteResult,
        operation_id="correctOfflineReceipt",
        responses=created,
        status_code=201,
        dependencies=[Depends(check_write)],
    )
    def correct_receipt(
        community_id: Identifier,
        bill_id: Identifier,
        entry_id: Identifier,
        data: schema.ReceiptCorrection,
        request: Request,
        key: Key,
        svc: Service,
        ctx: Annotated[AdminContext, permission("property.bill_receipt.correct")],
    ) -> schema.BillWriteResult:
        return svc.write(
            ctx,
            community_id,
            "correct_receipt",
            data,
            key,
            request.state.request_id,
            bill_id=bill_id,
            entry_id=entry_id,
        )

    @router.post(
        "/v1/communities/{community_id}/bills/{bill_id}/offline-receipts/{entry_id}/reversals",
        response_model=schema.BillWriteResult,
        operation_id="reverseOfflineReceipt",
        responses=created,
        status_code=201,
        dependencies=[Depends(check_write)],
    )
    def reverse_receipt(
        community_id: Identifier,
        bill_id: Identifier,
        entry_id: Identifier,
        data: schema.BillReasonAction,
        request: Request,
        key: Key,
        svc: Service,
        ctx: Annotated[AdminContext, permission("property.bill_receipt.correct")],
    ) -> schema.BillWriteResult:
        return svc.write(
            ctx,
            community_id,
            "reverse_receipt",
            data,
            key,
            request.state.request_id,
            bill_id=bill_id,
            entry_id=entry_id,
        )

    @router.get(
        "/v1/communities/{community_id}/bills/{bill_id}/settlement-entries",
        response_model=schema.SettlementEntryPage,
        operation_id="listBillSettlementEntries",
        responses=ok,
    )
    def list_entries(
        community_id: Identifier,
        bill_id: Identifier,
        svc: Service,
        ctx: Annotated[AdminContext, permission("property.bill.read")],
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    ) -> schema.SettlementEntryPage:
        return svc.list_entries(ctx, community_id, bill_id, page=page, page_size=page_size)

    @router.get(
        "/v1/communities/{community_id}/bills/{bill_id}/operations",
        response_model=schema.BillOperationPage,
        operation_id="listBillOperations",
        responses=ok,
    )
    def list_operations(
        community_id: Identifier,
        bill_id: Identifier,
        svc: Service,
        ctx: Annotated[AdminContext, permission("property.bill.read")],
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    ) -> schema.BillOperationPage:
        return svc.list_operations(ctx, community_id, bill_id, page=page, page_size=page_size)

    @router.get(
        "/v1/bill-operation-results/{idempotency_key}",
        response_model=schema.BillOperationResult,
        operation_id="getBillOperationResult",
        responses=ok,
    )
    def operation_result(
        idempotency_key: schema.IdempotencyKey,
        svc: Service,
        ctx: Annotated[AdminContext, permission("property.bill.read")],
    ) -> schema.BillOperationResult:
        return svc.operation_result(ctx, idempotency_key)

    return router
