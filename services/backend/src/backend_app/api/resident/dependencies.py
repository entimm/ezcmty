from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from backend_app.core.config import get_settings
from backend_app.core.openapi import get_problem_responses, get_request_id_headers
from backend_app.core.redis import get_redis
from backend_app.core.resident_sessions import ResidentContext, ResidentSessionStore
from backend_app.db.session import get_database_session
from backend_app.integrations.wechat_miniapp import WechatMiniapp
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
