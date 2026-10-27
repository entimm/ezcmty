from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Header, Query, Request, Response

from backend_app.api.client.dependencies import (
    Context,
    IdentityService,
    Service,
    Store,
    Wechat,
    client_responses,
)
from backend_app.schemas import miniapp as schema
from backend_app.schemas.admin import Identifier


def create_client_identity_router() -> APIRouter:
    router = APIRouter(prefix="/v1", tags=["miniapp"])

    @router.post(
        "/client-sessions",
        operation_id="createClientSession",
        status_code=201,
        response_model=schema.ClientSession,
        responses=client_responses(201),
    )
    def login(
        data: schema.MiniappLogin, request: Request, svc: Service, store: Store, wechat: Wechat
    ) -> schema.ClientSession:
        return svc.login(data, store, wechat, request.client.host if request.client else "unknown")

    @router.get(
        "/client-sessions/current",
        operation_id="getClientSession",
        response_model=schema.ClientSessionState,
        responses=client_responses(),
    )
    def session(ctx: Context, svc: Service) -> schema.ClientSessionState:
        return schema.ClientSessionState(
            user=svc.profile(ctx),
            expires_at=datetime.fromtimestamp(ctx.stored.absolute_expires_at, UTC),
        )

    @router.delete(
        "/client-sessions/current",
        operation_id="deleteClientSession",
        status_code=204,
        responses=client_responses(204),
    )
    def logout(ctx: Context, store: Store) -> Response:
        store.delete(ctx.token)
        return Response(status_code=204)

    @router.get(
        "/miniapp-users/me",
        operation_id="getMiniappUser",
        response_model=schema.MiniappUser,
        responses=client_responses(),
    )
    def me(ctx: Context, svc: Service) -> schema.MiniappUser:
        return svc.profile(ctx)

    @router.get(
        "/miniapp-users/me/phone-bindings",
        operation_id="listPhoneBindings",
        response_model=schema.PhoneBindingPage,
        responses=client_responses(),
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
        responses=client_responses(201),
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
        responses=client_responses(204),
    )
    def unbind(
        phone_binding_id: Identifier,
        ctx: Context,
        svc: Service,
        expected_row_version: Annotated[int, Query(ge=1, le=9007199254740991)],
    ) -> Response:
        svc.unbind_phone(ctx, phone_binding_id, expected_row_version)
        return Response(status_code=204)

    @router.get(
        "/miniapp-users/me/identities",
        operation_id="listMyClientIdentities",
        response_model=schema.ClientIdentityPage,
        responses=client_responses(errors=(401, 422, 500, 503)),
    )
    def identities(
        ctx: Context,
        svc: IdentityService,
        page: Annotated[int, Query(ge=1, le=9007199254740991)] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    ) -> schema.ClientIdentityPage:
        items, total = svc.list(ctx, page=page, page_size=page_size)
        return schema.ClientIdentityPage(
            items=[schema.ClientIdentity.model_validate(item) for item in items],
            total=total,
            page=page,
            page_size=page_size,
        )

    @router.get(
        "/miniapp-users/me/identities/{identity_id}",
        operation_id="getMyClientIdentity",
        response_model=schema.ClientIdentity,
        responses=client_responses(errors=(401, 403, 404, 422, 500, 503)),
    )
    def identity(
        identity_id: schema.ClientIdentityId, ctx: Context, svc: IdentityService
    ) -> schema.ClientIdentity:
        return schema.ClientIdentity.model_validate(svc.get(ctx, identity_id))

    return router
