from __future__ import annotations

import secrets
from collections.abc import Callable
from hashlib import sha256
from time import time
from typing import cast

from pydantic import BaseModel
from redis import Redis

from backend_app.core.config import Settings
from backend_app.core.errors import AppError
from backend_app.core.identifiers import normalize_uuid
from backend_app.core.session_store import RedisSessionStore
from backend_app.schemas.admin import AdminScope


class StoredAdminSession(BaseModel):
    session_version: int
    absolute_expires_at: float
    csrf_token: str


class AdminSessionStore:
    def __init__(self, client: Redis[str], settings: Settings):
        self.client = client
        self.settings = settings
        self.store = RedisSessionStore(client)

    def create(
        self, scope: AdminScope, account_id: str, version: int
    ) -> tuple[str, StoredAdminSession]:
        data = StoredAdminSession(
            session_version=version,
            absolute_expires_at=time() + self.settings.admin_session_absolute_seconds,
            csrf_token=secrets.token_urlsafe(32),
        )
        token = self.store.create_session(
            scope,
            normalize_uuid(account_id),
            data=data.model_dump(),
            ttl_seconds=self.settings.admin_session_idle_seconds,
        )
        return token, data

    def read(self, scope: AdminScope, token: str) -> tuple[str, StoredAdminSession] | None:
        try:
            session = self.store.get_session(scope, token)
            if session is None:
                return None
            account_id = normalize_uuid(session.subject_id)
            data = StoredAdminSession.model_validate(session.data)
        except ValueError:
            return None
        if data.absolute_expires_at <= time():
            self.delete(scope, token)
            return None
        return account_id, data

    def touch(self, scope: AdminScope, token: str, data: StoredAdminSession) -> None:
        remaining = int(data.absolute_expires_at - time())
        if remaining <= 0:
            raise AppError("auth.unauthenticated")
        # EXPIRE cannot recreate a session deleted by logout.
        if not self.client.expire(
            self.store._key(scope, token), min(remaining, self.settings.admin_session_idle_seconds)
        ):
            raise AppError("auth.unauthenticated")

    def delete(self, scope: AdminScope, token: str) -> None:
        self.store.delete_session(scope, token)

    def limit_login(self, scope: AdminScope, login_name: str, source_ip: str) -> None:
        keys = [
            f"app:admin-login:{scope}:{kind}:{sha256(value.encode()).hexdigest()}"
            for kind, value in (("account", login_name), ("ip", source_ip))
        ]
        script = """
        local exceeded = 0
        for _, key in ipairs(KEYS) do
            local count = redis.call('INCR', key)
            if count == 1 then redis.call('EXPIRE', key, ARGV[1]) end
            if count > tonumber(ARGV[2]) then exceeded = 1 end
        end
        return exceeded
        """
        evaluate = cast(Callable[..., object], self.client.eval)
        if evaluate(
            script,
            len(keys),
            *keys,
            self.settings.admin_login_window_seconds,
            self.settings.admin_login_limit,
        ):
            raise AppError("auth.rate_limited")
