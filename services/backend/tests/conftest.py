from collections.abc import Iterator

import pytest
from pytest import MonkeyPatch

from backend_app.core.config import get_settings
from backend_app.core.error_catalog import CONTRACT_VERSION
from backend_app.core.redis import get_redis
from backend_app.db.session import get_engine, get_session_factory


@pytest.fixture(autouse=True)
def configure_test_environment(monkeypatch: MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("APP_DATABASE_URL", "mysql+pymysql://127.0.0.1/test")
    monkeypatch.setenv("APP_REDIS_URL", "redis://127.0.0.1:6379/0")
    monkeypatch.setenv("APP_VERSION", CONTRACT_VERSION)
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()
    get_redis.cache_clear()
    yield
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()
    get_redis.cache_clear()
