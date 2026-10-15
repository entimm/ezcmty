from __future__ import annotations

import pytest
from pytest import MonkeyPatch

from backend_app.core.config import get_settings


@pytest.mark.parametrize(
    ("platform_path", "property_path"),
    [
        ("/api/admin", "/api/admin"),
        ("/api/admin", "/api/admin/"),
        ("/api/admin/", "/api/admin"),
        ("/api", "/api/admin"),
        ("/api/admin", "/api"),
        ("/", "/api/property"),
    ],
)
def test_overlapping_cookie_paths_are_rejected(
    monkeypatch: MonkeyPatch, platform_path: str, property_path: str
) -> None:
    monkeypatch.setenv("APP_PLATFORM_ADMIN_COOKIE_PATH", platform_path)
    monkeypatch.setenv("APP_PROPERTY_ADMIN_COOKIE_PATH", property_path)
    with pytest.raises(ValueError, match="cookie paths"):
        get_settings()


def test_sibling_cookie_paths_remain_isolated(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("APP_PLATFORM_ADMIN_COOKIE_PATH", "/api/admin")
    monkeypatch.setenv("APP_PROPERTY_ADMIN_COOKIE_PATH", "/api/admin-property")
    settings = get_settings()
    assert settings.platform_admin_cookie_path == "/api/admin"
    assert settings.property_admin_cookie_path == "/api/admin-property"
