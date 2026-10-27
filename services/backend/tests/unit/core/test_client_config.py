import pytest

from backend_app.core.config import get_settings


def test_client_configuration_uses_new_names_and_preserves_resident_claim_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_CLIENT_SESSION_IDLE_SECONDS", "120")
    monkeypatch.setenv("APP_CLIENT_SESSION_ABSOLUTE_SECONDS", "240")
    monkeypatch.setenv("APP_CLIENT_LOGIN_LIMIT", "7")
    monkeypatch.setenv("APP_CLIENT_PHONE_LIMIT", "8")
    monkeypatch.setenv("APP_CLIENT_RATE_WINDOW_SECONDS", "90")
    monkeypatch.setenv("APP_RESIDENT_CLAIM_LIMIT", "9")
    settings = get_settings()
    assert settings.client_session_idle_seconds == 120
    assert settings.client_session_absolute_seconds == 240
    assert settings.client_login_limit == 7
    assert settings.client_phone_limit == 8
    assert settings.client_rate_window_seconds == 90
    assert settings.resident_claim_limit == 9


def test_client_absolute_lifetime_must_cover_idle_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_CLIENT_SESSION_IDLE_SECONDS", "240")
    monkeypatch.setenv("APP_CLIENT_SESSION_ABSOLUTE_SECONDS", "120")
    with pytest.raises(ValueError, match="Client absolute lifetime"):
        get_settings()
