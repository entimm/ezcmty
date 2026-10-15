from __future__ import annotations

import json
from pathlib import Path

from pytest import MonkeyPatch


def test_explicit_backend_env_and_environment_priority(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    from scripts.dev.services import dependency_probe

    from backend_app.core import readiness as system
    from backend_app.core.config import get_settings

    backend = tmp_path / "backend"
    backend.mkdir()
    monkeypatch.setenv("APP_LOG_LEVEL", "INFO")
    (backend / ".env").write_text(
        "APP_DATABASE_URL=mysql+pymysql://env-user:secret@127.0.0.1/existing\n"
        "APP_REDIS_URL=redis://127.0.0.1:6379/4\n"
    )
    (tmp_path / ".env").write_text("APP_DATABASE_URL=wrong-root-file\n")
    monkeypatch.delenv("APP_DATABASE_URL")
    monkeypatch.delenv("APP_REDIS_URL")
    monkeypatch.chdir(backend)
    monkeypatch.setattr(system, "check_readiness", lambda: {"mysql": "ok", "redis": "ok"})
    get_settings.cache_clear()
    assert dependency_probe()["ok"]
    assert get_settings().redis_url.get_secret_value().endswith("/4")
    monkeypatch.setenv("APP_REDIS_URL", "redis://127.0.0.1:6379/9")
    get_settings.cache_clear()
    assert dependency_probe()["ok"]
    assert get_settings().redis_url.get_secret_value().endswith("/9")
    assert "secret" not in json.dumps(dependency_probe())
