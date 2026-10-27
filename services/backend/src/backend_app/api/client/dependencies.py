from typing import Annotated, Any

from fastapi import Depends, Header
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from backend_app.core.client_sessions import ClientSessionStore
from backend_app.core.config import get_settings
from backend_app.core.openapi import get_problem_responses, get_request_id_headers
from backend_app.core.redis import get_redis
from backend_app.db.session import get_database_session
from backend_app.domain.client.types import ClientAuthorization
from backend_app.integrations.wechat_miniapp import WechatMiniapp
from backend_app.schemas.miniapp import ClientIdentityId
from backend_app.services.client.identities import ClientIdentityRegistry, ClientIdentityService
from backend_app.services.client.identity import ClientAccountService
from backend_app.services.contracts.client import ClientContext

bearer = HTTPBearer(scheme_name="ClientToken", auto_error=False)


def get_client_session_store() -> ClientSessionStore:
    return ClientSessionStore(get_redis(), get_settings())


def get_client_identity_registry() -> ClientIdentityRegistry:
    return ClientIdentityRegistry()


def get_wechat_miniapp(
    store: Annotated[ClientSessionStore, Depends(get_client_session_store)],
) -> WechatMiniapp:
    return WechatMiniapp(store.settings, store.client)


def account_service(db: Annotated[Session, Depends(get_database_session)]) -> ClientAccountService:
    return ClientAccountService(db)


def identity_service(
    db: Annotated[Session, Depends(get_database_session)],
    registry: Annotated[ClientIdentityRegistry, Depends(get_client_identity_registry)],
) -> ClientIdentityService:
    return ClientIdentityService(db, registry)


Service = Annotated[ClientAccountService, Depends(account_service)]
IdentityService = Annotated[ClientIdentityService, Depends(identity_service)]
Store = Annotated[ClientSessionStore, Depends(get_client_session_store)]
Wechat = Annotated[WechatMiniapp, Depends(get_wechat_miniapp)]


def client_context(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    store: Store,
    svc: Service,
) -> ClientContext:
    ctx = store.authenticate(credentials.credentials if credentials else None)
    svc.profile(ctx)
    return ctx


Context = Annotated[ClientContext, Depends(client_context)]


def resident_context(
    ctx: Context,
    identities: IdentityService,
    identity_id: Annotated[ClientIdentityId, Header(alias="X-Client-Identity")],
) -> ClientAuthorization:
    return identities.authorize(ctx, identity_id, expected_type="resident")


ResidentContext = Annotated[ClientAuthorization, Depends(resident_context)]


def client_responses(
    status: int = 200, *, errors: tuple[int, ...] | None = None
) -> dict[int | str, Any]:
    statuses = errors if errors is not None else (401, 403, 404, 409, 422, 429, 500, 503)
    responses = get_problem_responses(*statuses)
    for code, response in responses.items():
        response["headers"]["Cache-Control"] = {"schema": {"type": "string", "const": "no-store"}}
        if code == 401:
            response["headers"]["WWW-Authenticate"] = {
                "schema": {"type": "string", "const": "Bearer"}
            }
        if code == 429:
            response["headers"]["Retry-After"] = {"schema": {"type": "integer", "minimum": 1}}
    responses[status] = {
        "headers": {
            **get_request_id_headers(),
            "Cache-Control": {"schema": {"type": "string", "const": "no-store"}},
        }
    }
    return responses
