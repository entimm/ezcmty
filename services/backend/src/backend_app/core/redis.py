from __future__ import annotations

from functools import lru_cache

from redis import Redis

from backend_app.core.config import get_settings


@lru_cache(maxsize=1)
def get_redis() -> Redis[str]:
    return Redis.from_url(
        get_settings().redis_url.get_secret_value(),
        decode_responses=True,
        socket_connect_timeout=3,
        socket_timeout=3,
    )
