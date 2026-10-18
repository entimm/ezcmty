from collections.abc import Callable
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.params import Depends as DependsParameter
from pydantic import WithJsonSchema
from sqlalchemy.orm import Session

from backend_app.api.payment_headers import no_store, required_write_headers
from backend_app.core.config import get_settings
from backend_app.core.openapi import get_problem_responses, get_request_id_headers
from backend_app.db.session import get_database_session
from backend_app.schemas.admin import Identifier
from backend_app.schemas.payments import configuration as schema
from backend_app.schemas.payments.base import IdempotencyKey
from backend_app.services.contracts.admin import AdminContext
from backend_app.services.platform_admin.payment_configuration import PaymentConfigurationService


def create_payment_configuration_router(
    permission: Callable[[str], DependsParameter], check_write: Callable[..., None]
) -> APIRouter:
    router = APIRouter(
        prefix="/v1/property-companies/{company_id}",
        tags=["payment-management"],
        dependencies=[Depends(no_store)],
    )
    errors = get_problem_responses(401, 403, 404, 409, 422, 500, 503)
    headers = {
        **get_request_id_headers(),
        "Cache-Control": {"schema": {"type": "string", "const": "no-store"}},
    }
    ok = {**errors, 200: {"headers": headers}}
    created = {**errors, 201: {"headers": headers}}

    def service(
        db: Annotated[Session, Depends(get_database_session)],
    ) -> PaymentConfigurationService:
        return PaymentConfigurationService(db, get_settings())

    Service = Annotated[PaymentConfigurationService, Depends(service)]

    @router.get(
        "/merchant-bindings",
        operation_id="listCompanyMerchantBindings",
        response_model=schema.MerchantBindingPage,
        responses=ok,
    )
    def bindings(
        company_id: Identifier,
        svc: Service,
        ctx: Annotated[AdminContext, permission("platform.payment_config.read")],
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 20,
        sort: Literal["created_at,id", "-created_at,-id"] = "-created_at,-id",
        enabled: Annotated[bool | None, WithJsonSchema({"type": "boolean"})] = None,
    ) -> schema.MerchantBindingPage:
        return svc.bindings(
            ctx, company_id, page=page, page_size=page_size, sort=sort, enabled=enabled
        )

    @router.post(
        "/merchant-bindings",
        operation_id="createCompanyMerchantBinding",
        response_model=schema.MerchantBinding,
        status_code=201,
        responses=created,
        dependencies=[Depends(check_write), Depends(required_write_headers)],
    )
    def create_binding(
        company_id: Identifier,
        data: schema.MerchantBindingCreate,
        request: Request,
        svc: Service,
        ctx: Annotated[AdminContext, permission("platform.payment_config.manage")],
        key: Annotated[IdempotencyKey, Header(alias="Idempotency-Key")],
    ) -> schema.MerchantBinding:
        return svc.create_binding(ctx, company_id, data, key, request.state.request_id)

    @router.get(
        "/payment-configuration",
        operation_id="getCompanyPaymentConfiguration",
        response_model=schema.PaymentConfiguration,
        responses=ok,
    )
    def configuration(
        company_id: Identifier,
        svc: Service,
        ctx: Annotated[AdminContext, permission("platform.payment_config.read")],
    ) -> schema.PaymentConfiguration:
        return svc.get(ctx, company_id)

    @router.put(
        "/active-merchant-binding",
        operation_id="replaceCompanyActiveMerchantBinding",
        response_model=schema.PaymentConfiguration,
        responses=ok,
        dependencies=[Depends(check_write), Depends(required_write_headers)],
    )
    def activate(
        company_id: Identifier,
        data: schema.ActiveMerchantBindingUpdate,
        request: Request,
        svc: Service,
        ctx: Annotated[AdminContext, permission("platform.payment_config.manage")],
    ) -> schema.PaymentConfiguration:
        return svc.activate(ctx, company_id, data, request.state.request_id)

    @router.get(
        "/profit-sharing-rule-versions",
        operation_id="listCompanyProfitSharingRuleVersions",
        response_model=schema.ProfitSharingRuleVersionPage,
        responses=ok,
    )
    def rules(
        company_id: Identifier,
        svc: Service,
        ctx: Annotated[AdminContext, permission("platform.payment_config.read")],
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 20,
        sort: Literal["version_no,id", "-version_no,-id"] = "-version_no,-id",
    ) -> schema.ProfitSharingRuleVersionPage:
        return svc.rules(ctx, company_id, page=page, page_size=page_size, sort=sort)

    @router.post(
        "/profit-sharing-rule-versions",
        operation_id="createCompanyProfitSharingRuleVersion",
        response_model=schema.ProfitSharingRuleVersion,
        status_code=201,
        responses=created,
        dependencies=[Depends(check_write), Depends(required_write_headers)],
    )
    def create_rule(
        company_id: Identifier,
        data: schema.ProfitSharingRuleCreate,
        request: Request,
        svc: Service,
        ctx: Annotated[AdminContext, permission("platform.payment_config.manage")],
        key: Annotated[IdempotencyKey, Header(alias="Idempotency-Key")],
    ) -> schema.ProfitSharingRuleVersion:
        return svc.create_rule(ctx, company_id, data, key, request.state.request_id)

    @router.get(
        "/profit-sharing-rule-versions/{version_id}",
        operation_id="getCompanyProfitSharingRuleVersion",
        response_model=schema.ProfitSharingRuleVersion,
        responses=ok,
    )
    def rule(
        company_id: Identifier,
        version_id: Identifier,
        svc: Service,
        ctx: Annotated[AdminContext, permission("platform.payment_config.read")],
    ) -> schema.ProfitSharingRuleVersion:
        return svc.rule(ctx, company_id, version_id)

    return router
