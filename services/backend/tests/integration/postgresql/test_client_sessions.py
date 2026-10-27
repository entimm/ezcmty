import json
from hashlib import sha256

import pytest
from sqlalchemy.orm import Session, sessionmaker

from backend_app.core.admin_sessions import AdminSessionStore
from backend_app.core.client_sessions import ClientSessionStore
from backend_app.core.errors import AppError
from backend_app.core.identifiers import new_id
from backend_app.core.session_store import SessionData, SessionScope


def test_old_resident_scope_is_not_accepted_even_with_matching_payload(
    real_admin: tuple[sessionmaker[Session], AdminSessionStore],
) -> None:
    _, admin = real_admin
    store = ClientSessionStore(admin.client, admin.settings)
    token, stored = store.create(new_id(), 1)
    client_key = store.store._key("client", token)
    raw = admin.client.get(client_key)
    assert raw is not None
    old_key = f"app:session:resident:{sha256(token.encode()).hexdigest()}"
    admin.client.setex(old_key, 60, raw)
    admin.client.delete(client_key)
    with pytest.raises(AppError) as caught:
        store.authenticate(token)
    assert caught.value.code == "auth.unauthenticated"
    assert admin.client.get(old_key) == raw
    assert token not in old_key + raw
    assert stored.version == 1


@pytest.mark.parametrize("invalid", ['{"version":0,"absolute_expires_at":9999999999}', "{}"])
def test_invalid_client_session_payload_is_unauthenticated(
    real_admin: tuple[sessionmaker[Session], AdminSessionStore], invalid: str
) -> None:
    _, admin = real_admin
    store = ClientSessionStore(admin.client, admin.settings)
    token, _ = store.create(new_id(), 1)
    key = store.store._key("client", token)
    raw = json.loads(admin.client.get(key) or "{}")
    raw["data"] = json.loads(invalid)
    admin.client.setex(key, 60, json.dumps(raw))
    with pytest.raises(AppError) as caught:
        store.authenticate(token)
    assert caught.value.code == "auth.unauthenticated"


def test_deleted_redis_session_cannot_be_revived_by_idle_refresh(
    real_admin: tuple[sessionmaker[Session], AdminSessionStore],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, admin = real_admin
    store = ClientSessionStore(admin.client, admin.settings)
    token, _ = store.create(new_id(), 1)
    original_get = store.store.get_session

    def get_then_delete(scope: SessionScope, token: str) -> SessionData | None:
        result = original_get(scope, token)
        store.delete(token)
        return result

    monkeypatch.setattr(store.store, "get_session", get_then_delete)
    with pytest.raises(AppError) as caught:
        store.authenticate(token)
    assert caught.value.code == "auth.unauthenticated"
