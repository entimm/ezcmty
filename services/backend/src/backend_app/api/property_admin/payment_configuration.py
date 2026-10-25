from collections.abc import Callable
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response
from fastapi.params import Depends as DependsParameter
from pydantic import WithJsonSchema
from sqlalchemy.orm import Session

from backend_app.core.config import get_settings
from backend_app.core.openapi import get_problem_responses, get_request_id_headers
from backend_app.db.session import get_database_session
from backend_app.schemas.admin import Identifier
from backend_app.schemas.payments import configuration as schema
from backend_app.services.contracts.admin import AdminContext
from backend_app.services.property_admin.payment_configuration import (
    PropertyPaymentConfigurationService,
)


def create_property_payment_configuration_router(
    permission: Callable[[str], DependsParameter],
) -> APIRouter:
    def no_store(response: Response) -> None:
        response.headers["Cache-Control"] = "no-store"

    router = APIRouter(prefix="/v1", tags=["payment-management"], dependencies=[Depends(no_store)])
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
    ) -> PropertyPaymentConfigurationService:
        return PropertyPaymentConfigurationService(db, get_settings())

    Service = Annotated[PropertyPaymentConfigurationService, Depends(service)]

    @router.get(
        "/merchant-bindings",
        operation_id="listCurrentCompanyMerchantBindings",
        response_model=schema.MerchantBindingPage,
        responses=ok,
    )
    def bindings(
        svc: Service,
        ctx: Annotated[AdminContext, permission("property.payment.read")],
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 20,
        sort: Literal["created_at,id", "-created_at,-id"] = "-created_at,-id",
        enabled: Annotated[bool | None, WithJsonSchema({"type": "boolean"})] = None,
    ) -> schema.MerchantBindingPage:
        return svc.bindings(ctx, page=page, page_size=page_size, sort=sort, enabled=enabled)

    @router.get(
        "/payment-configuration",
        operation_id="getCurrentCompanyPaymentConfiguration",
        response_model=schema.PaymentConfiguration,
        responses=ok,
    )
    def configuration(
        svc: Service, ctx: Annotated[AdminContext, permission("property.payment.read")]
    ) -> schema.PaymentConfiguration:
        return svc.get(ctx)

    @router.get(
        "/profit-sharing-rule-versions",
        operation_id="listCurrentCompanyProfitSharingRuleVersions",
        response_model=schema.ProfitSharingRuleVersionPage,
        responses=ok,
    )
    def rules(
        svc: Service,
        ctx: Annotated[AdminContext, permission("property.payment.read")],
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 20,
        sort: Literal["version_no,id", "-version_no,-id"] = "-version_no,-id",
    ) -> schema.ProfitSharingRuleVersionPage:
        return svc.rules(ctx, page=page, page_size=page_size, sort=sort)

    @router.get(
        "/profit-sharing-rule-versions/{version_id}",
        operation_id="getCurrentCompanyProfitSharingRuleVersion",
        response_model=schema.ProfitSharingRuleVersion,
        responses=ok,
    )
    def rule(
        version_id: Identifier,
        svc: Service,
        ctx: Annotated[AdminContext, permission("property.payment.read")],
    ) -> schema.ProfitSharingRuleVersion:
        return svc.rule(ctx, version_id)

    return router
