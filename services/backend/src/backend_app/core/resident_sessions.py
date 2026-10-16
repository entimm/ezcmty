from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from time import time
from typing import cast

from pydantic import BaseModel
from redis import Redis

from backend_app.core.config import Settings
from backend_app.core.errors import AppError
from backend_app.core.identifiers import normalize_uuid
from backend_app.core.session_store import RedisSessionStore


class StoredResidentSession(BaseModel):
    version: int
    absolute_expires_at: float


@dataclass(frozen=True)
class ResidentContext:
    user_id: str
    version: int
    token: str
    stored: StoredResidentSession


class ResidentSessionStore:
    def __init__(self, client: Redis[str], settings: Settings, *, key_prefix: str = "app"):
        self.client = client
        self.settings = settings
        self.key_prefix = key_prefix
        self.store = RedisSessionStore(client, key_prefix=f"{key_prefix}:session")

    def create(self, user_id: str, version: int) -> tuple[str, StoredResidentSession]:
        data = StoredResidentSession(
            version=version,
            absolute_expires_at=time() + self.settings.resident_session_absolute_seconds,
        )
        token = self.store.create_session(
            "resident",
            normalize_uuid(user_id),
            data=data.model_dump(),
            ttl_seconds=self.settings.resident_session_idle_seconds,
        )
        return token, data

    def authenticate(self, token: str | None) -> ResidentContext:
        if not token:
            raise AppError("auth.unauthenticated")
        try:
            value = self.store.get_session("resident", token)
            if value is None:
                raise ValueError("Missing session")
            stored = StoredResidentSession.model_validate(value.data)
            user_id = normalize_uuid(value.subject_id)
        except ValueError:
            raise AppError("auth.unauthenticated") from None
        remaining = int(stored.absolute_expires_at - time())
        if remaining <= 0 or not self.client.expire(
            self.store._key("resident", token),
            min(remaining, self.settings.resident_session_idle_seconds),
        ):
            raise AppError("auth.unauthenticated")
        return ResidentContext(user_id, stored.version, token, stored)

    def delete(self, token: str) -> None:
        self.store.delete_session("resident", token)

    def limit(self, action: str, subject: str, limit: int) -> None:
        # Counter TTL is fixed, so Retry-After can report the remaining window.
        key = f"{self.key_prefix}:resident-rate:{action}:{sha256(subject.encode()).hexdigest()}"
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
            self.settings.resident_rate_window_seconds,
            limit,
        )
        if result:
            raise AppError("resident.rate_limited", retry_after=int(result))
