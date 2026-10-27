from collections.abc import Callable
from hashlib import sha256
from time import time
from typing import cast

from redis import Redis

from backend_app.core.config import Settings
from backend_app.core.errors import AppError
from backend_app.core.identifiers import normalize_uuid
from backend_app.core.session_store import RedisSessionStore
from backend_app.services.contracts.client import ClientContext, StoredClientSession


class ClientSessionStore:
    def __init__(self, client: Redis[str], settings: Settings, *, key_prefix: str = "app"):
        self.client = client
        self.settings = settings
        self.key_prefix = key_prefix
        self.store = RedisSessionStore(client, key_prefix=f"{key_prefix}:session")

    def create(self, user_id: str, version: int) -> tuple[str, StoredClientSession]:
        data = StoredClientSession(
            version=version,
            absolute_expires_at=time() + self.settings.client_session_absolute_seconds,
        )
        token = self.store.create_session(
            "client",
            normalize_uuid(user_id),
            data=data.model_dump(),
            ttl_seconds=self.settings.client_session_idle_seconds,
        )
        return token, data

    def authenticate(self, token: str | None) -> ClientContext:
        if not token:
            raise AppError("auth.unauthenticated")
        try:
            value = self.store.get_session("client", token)
            if value is None:
                raise ValueError("Missing session")
            stored = StoredClientSession.model_validate(value.data)
            user_id = normalize_uuid(value.subject_id)
        except ValueError:
            raise AppError("auth.unauthenticated") from None
        remaining = int(stored.absolute_expires_at - time())
        if remaining <= 0 or not self.client.expire(
            self.store._key("client", token),
            min(remaining, self.settings.client_session_idle_seconds),
        ):
            raise AppError("auth.unauthenticated")
        return ClientContext(user_id, stored.version, token, stored)

    def delete(self, token: str) -> None:
        self.store.delete_session("client", token)

    def limit(self, action: str, subject: str, limit: int) -> None:
        # Counter TTL is fixed, so Retry-After can report the remaining window.
        key = f"{self.key_prefix}:client-rate:{action}:{sha256(subject.encode()).hexdigest()}"
        evaluate = cast(Callable[..., int], self.client.eval)
        result = evaluate(
            """
            local count = redis.call('INCR', KEYS[1])
            if count == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
            if count > tonumber(ARGV[2]) then return math.max(1, redis.call('TTL', KEYS[1])) end
            return 0
        """,
            1,
            key,
            self.settings.client_rate_window_seconds,
            limit,
        )
        if result:
            raise AppError("resident.rate_limited", retry_after=int(result))
