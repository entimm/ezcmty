from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from backend_app.core.config import get_settings
from backend_app.core.openapi import get_problem_responses, get_request_id_headers
from backend_app.core.redis import get_redis
from backend_app.core.resident_sessions import ResidentContext, ResidentSessionStore
from backend_app.db.session import get_database_session
from backend_app.integrations.wechat_miniapp import WechatMiniapp
from backend_app.schemas import miniapp as schema
from backend_app.schemas.admin import Identifier
from backend_app.services.resident.identity import ResidentIdentityService

bearer = HTTPBearer(scheme_name="ResidentToken", auto_error=False)


def get_resident_session_store() -> ResidentSessionStore:
    return ResidentSessionStore(get_redis(), get_settings())


def get_wechat_miniapp(
    store: Annotated[ResidentSessionStore, Depends(get_resident_session_store)],
) -> WechatMiniapp:
    return WechatMiniapp(store.settings, store.client)


def identity_service(
    db: Annotated[Session, Depends(get_database_session)],
) -> ResidentIdentityService:
    return ResidentIdentityService(db)


Service = Annotated[ResidentIdentityService, Depends(identity_service)]
Store = Annotated[ResidentSessionStore, Depends(get_resident_session_store)]
Wechat = Annotated[WechatMiniapp, Depends(get_wechat_miniapp)]


def resident_context(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    store: Store,
    svc: Service,
) -> ResidentContext:
    ctx = store.authenticate(credentials.credentials if credentials else None)
    svc.profile(ctx)
    return ctx


Context = Annotated[ResidentContext, Depends(resident_context)]


def resident_responses(status: int = 200) -> dict[int | str, dict[str, object]]:
    responses = get_problem_responses(401, 403, 404, 409, 422, 429, 500, 503)
    responses[429]["headers"]["Retry-After"] = {"schema": {"type": "integer", "minimum": 1}}
    responses[status] = {"headers": get_request_id_headers()}
    return responses


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
