from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from backend_app.app_factory import create_app
from backend_app.core.config import get_settings
from backend_app.core.redis import get_redis
from backend_app.db.session import get_engine


def test_health_endpoint(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("APP_DATABASE_URL", "postgresql+psycopg://user:password@localhost:5432/app")
    monkeypatch.setenv("APP_REDIS_URL", "redis://localhost:6379/0")
    get_settings.cache_clear()

    client = TestClient(create_app("test-service"))
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "test-service"}
    assert response.headers["x-request-id"]


def test_readiness_reports_unavailable_dependencies(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("APP_DATABASE_URL", "postgresql+psycopg://user:password@127.0.0.1:1/app")
    monkeypatch.setenv("APP_REDIS_URL", "redis://127.0.0.1:1/0")
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_redis.cache_clear()

    client = TestClient(create_app("test-service"))
    response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert response.json()["dependencies"] == {"postgresql": "unavailable", "redis": "unavailable"}
