from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.params import Depends as DependsParameter
from sqlalchemy.orm import Session

from backend_app.api.payment_headers import no_store, required_write_headers
from backend_app.core.openapi import get_problem_responses, get_request_id_headers
from backend_app.db.session import get_database_session
from backend_app.schemas.admin import Identifier
from backend_app.schemas.payments import management as schema
from backend_app.services.contracts.admin import AdminContext
from backend_app.services.platform_admin.payment_recovery import PaymentRecoveryService


def create_payment_recovery_router(
    permission: Callable[[str], DependsParameter], check_write: Callable[..., None]
) -> APIRouter:
    router = APIRouter(
        prefix="/v1",
        tags=["payment-management"],
        dependencies=[Depends(no_store), Depends(check_write), Depends(required_write_headers)],
    )
    headers = {
        **get_request_id_headers(),
        "Cache-Control": {"schema": {"type": "string", "const": "no-store"}},
    }
    errors = get_problem_responses(401, 403, 404, 409, 422, 500, 503)
    accepted = {**errors, 202: {"headers": headers}}

    def service(db: Annotated[Session, Depends(get_database_session)]) -> PaymentRecoveryService:
        return PaymentRecoveryService(db)

    Service = Annotated[PaymentRecoveryService, Depends(service)]

    @router.post(
        "/payment-orders/{payment_order_id}/recoveries",
        operation_id="recoverManagedPaymentOrder",
        response_model=schema.PaymentRecoveryAccepted,
        status_code=202,
        responses=accepted,
    )
    def payment(
        payment_order_id: Identifier,
        data: schema.PaymentRecoveryRequest,
        request: Request,
        svc: Service,
        ctx: Annotated[AdminContext, permission("platform.payment.recover")],
    ) -> schema.PaymentRecoveryAccepted:
        return svc.payment(ctx, payment_order_id, data, request.state.request_id)

    @router.post(
        "/payment-reconciliation-runs/{reconciliation_run_id}/rechecks",
        operation_id="recheckManagedReconciliationRun",
        response_model=schema.PaymentRecoveryAccepted,
        status_code=202,
        responses=accepted,
    )
    def run(
        reconciliation_run_id: Identifier,
        data: schema.PaymentRecoveryRequest,
        request: Request,
        svc: Service,
        ctx: Annotated[AdminContext, permission("platform.payment_reconciliation.manage")],
    ) -> schema.PaymentRecoveryAccepted:
        return svc.run(ctx, reconciliation_run_id, data, request.state.request_id)

    @router.post(
        "/payment-reconciliation-discrepancies/{discrepancy_id}/recoveries",
        operation_id="recoverManagedReconciliationDiscrepancy",
        response_model=schema.PaymentRecoveryAccepted,
        status_code=202,
        responses=accepted,
    )
    def discrepancy(
        discrepancy_id: Identifier,
        data: schema.PaymentRecoveryRequest,
        request: Request,
        svc: Service,
        ctx: Annotated[AdminContext, permission("platform.payment.recover")],
    ) -> schema.PaymentRecoveryAccepted:
        return svc.discrepancy(ctx, discrepancy_id, data, request.state.request_id)

    @router.post(
        "/payment-reconciliation-discrepancies/{discrepancy_id}/external-resolutions",
        operation_id="recordManagedReconciliationExternalResolution",
        response_model=schema.ManagedReconciliationDiscrepancy,
        responses={**errors, 200: {"headers": headers}},
        dependencies=[permission("platform.payment_reconciliation.read")],
    )
    def external_resolution(
        discrepancy_id: Identifier,
        data: schema.ReconciliationExternalResolutionRequest,
        request: Request,
        svc: Service,
        ctx: Annotated[AdminContext, permission("platform.payment.recover")],
    ) -> schema.ManagedReconciliationDiscrepancy:
        return svc.external_resolution(ctx, discrepancy_id, data, request.state.request_id)

    return router
