from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Header, Query, Request, Response

from backend_app.api.resident.dependencies import (
    Context,
    Service,
    Store,
    Wechat,
    resident_responses,
)
from backend_app.schemas import miniapp as schema
from backend_app.schemas.admin import Identifier


def create_resident_identity_router() -> APIRouter:
    router = APIRouter(prefix="/v1", tags=["miniapp"])

    @router.post(
        "/resident-sessions",
        operation_id="createResidentSession",
        status_code=201,
        response_model=schema.ResidentSession,
        responses=resident_responses(201),
    )
    def login(
        data: schema.MiniappLogin, request: Request, svc: Service, store: Store, wechat: Wechat
    ) -> schema.ResidentSession:
        return svc.login(data, store, wechat, request.client.host if request.client else "unknown")

    @router.get(
        "/resident-sessions/current",
        operation_id="getResidentSession",
        response_model=schema.ResidentSessionState,
        responses=resident_responses(),
    )
    def session(ctx: Context, svc: Service) -> schema.ResidentSessionState:
        return schema.ResidentSessionState(
            user=svc.profile(ctx),
            expires_at=datetime.fromtimestamp(ctx.stored.absolute_expires_at, UTC),
        )

    @router.delete(
        "/resident-sessions/current",
        operation_id="deleteResidentSession",
        status_code=204,
        responses=resident_responses(204),
    )
    def logout(ctx: Context, store: Store) -> Response:
        store.delete(ctx.token)
        return Response(status_code=204)

    @router.get(
        "/miniapp-users/me",
        operation_id="getMiniappUser",
        response_model=schema.MiniappUser,
        responses=resident_responses(),
    )
    def me(ctx: Context, svc: Service) -> schema.MiniappUser:
        return svc.profile(ctx)

    @router.get(
        "/miniapp-users/me/phone-bindings",
        operation_id="listPhoneBindings",
        response_model=schema.PhoneBindingPage,
        responses=resident_responses(),
    )
    def phones(
        ctx: Context,
        svc: Service,
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    ) -> schema.PhoneBindingPage:
        return svc.list_phones(ctx, page, page_size)

    @router.post(
        "/miniapp-users/me/phone-bindings",
        operation_id="createPhoneBinding",
        status_code=201,
        response_model=schema.PhoneBinding,
        responses=resident_responses(201),
    )
    def bind(
        data: schema.PhoneBindingCreate,
        request: Request,
        ctx: Context,
        svc: Service,
        store: Store,
        wechat: Wechat,
        idempotency_key: Annotated[schema.IdempotencyKey, Header(alias="Idempotency-Key")],
    ) -> schema.PhoneBinding:
        return svc.bind_phone(ctx, data, idempotency_key, request.state.request_id, store, wechat)

    @router.delete(
        "/miniapp-users/me/phone-bindings/{phone_binding_id}",
        operation_id="deletePhoneBinding",
        status_code=204,
        responses=resident_responses(204),
    )
    def unbind(
        phone_binding_id: Identifier,
        ctx: Context,
        svc: Service,
        expected_row_version: Annotated[int, Query(ge=1, le=9007199254740991)],
    ) -> Response:
        svc.unbind_phone(ctx, phone_binding_id, expected_row_version)
        return Response(status_code=204)

    return router
