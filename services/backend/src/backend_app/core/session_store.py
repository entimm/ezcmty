from __future__ import annotations

import json
import secrets
from hashlib import sha256
from typing import Literal

from pydantic import BaseModel
from redis import Redis

SessionScope = Literal["platform_admin", "property_admin", "resident"]


class SessionData(BaseModel):
    subject_id: str
    data: dict[str, object]


class RedisSessionStore:
    def __init__(self, client: Redis[str], *, key_prefix: str = "app:session") -> None:
        self.client = client
        self.key_prefix = key_prefix

    def _key(self, scope: SessionScope, token: str) -> str:
        if scope not in ("platform_admin", "property_admin", "resident"):
            raise ValueError("Invalid session scope")
        token_hash = sha256(token.encode()).hexdigest()
        return f"{self.key_prefix}:{scope}:{token_hash}"

    def create_session(
        self,
        scope: SessionScope,
        subject_id: str,
        *,
        data: dict[str, object] | None = None,
        ttl_seconds: int,
    ) -> str:
        if ttl_seconds <= 0:
            raise ValueError("Session TTL must be positive")
        token = secrets.token_urlsafe(32)
        payload = {"subject_id": subject_id, "data": data or {}}
        self.client.setex(self._key(scope, token), ttl_seconds, json.dumps(payload))
        return token

    def get_session(self, scope: SessionScope, token: str) -> SessionData | None:
        raw = self.client.get(self._key(scope, token))
        if raw is None:
            return None
        return SessionData.model_validate_json(raw)

    def delete_session(self, scope: SessionScope, token: str) -> None:
        self.client.delete(self._key(scope, token))
