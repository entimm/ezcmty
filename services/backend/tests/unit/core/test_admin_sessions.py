from __future__ import annotations

from typing import cast

import pytest
from redis import Redis
from tests.support.redis import MemoryRedis

from backend_app.core.admin_sessions import AdminSessionStore
from backend_app.core.config import get_settings
from backend_app.core.errors import AppError
from backend_app.core.identifiers import new_id


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> AdminSessionStore:
    redis = MemoryRedis()
    monkeypatch.setattr("backend_app.core.admin_sessions.time", lambda: redis.now)
    settings = get_settings().model_copy(
        update={
            "admin_session_idle_seconds": 60,
            "admin_session_absolute_seconds": 120,
            "admin_login_limit": 2,
        }
    )
    return AdminSessionStore(cast("Redis[str]", redis), settings)


def test_absolute_expiry_is_not_extended_by_activity(store: AdminSessionStore) -> None:
    redis = cast(MemoryRedis, store.client)
    token, stored = store.create("platform_admin", new_id(), 1)
    redis.now += 50
    store.touch("platform_admin", token, stored)
    redis.now += 50
    store.touch("platform_admin", token, stored)
    redis.now += 21
    assert store.read("platform_admin", token) is None


def test_idle_session_expires(store: AdminSessionStore) -> None:
    redis = cast(MemoryRedis, store.client)
    token, _ = store.create("platform_admin", new_id(), 1)
    redis.now += 61
    assert store.read("platform_admin", token) is None


def test_login_limit_rejects_excess_attempt(store: AdminSessionStore) -> None:
    store.limit_login("platform_admin", "account", "source")
    store.limit_login("platform_admin", "account", "source")
    with pytest.raises(AppError) as caught:
        store.limit_login("platform_admin", "account", "source")
    assert caught.value.code == "auth.rate_limited"


def test_login_case_variants_share_account_limit_across_source_ips(
    store: AdminSessionStore,
) -> None:
    store.limit_login("platform_admin", "Admin", "first-ip")
    store.limit_login("platform_admin", "ADMIN", "second-ip")
    with pytest.raises(AppError) as caught:
        store.limit_login("platform_admin", "admin", "third-ip")
    assert caught.value.code == "auth.rate_limited"
    store.limit_login("property_admin", "ADMIN", "fourth-ip")
