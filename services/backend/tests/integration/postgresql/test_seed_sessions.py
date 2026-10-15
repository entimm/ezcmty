from __future__ import annotations

import secrets

import pytest
from devtools.seed.runner import REDIS_KEY_PREFIX
from devtools.seed.runtime import Actor
from sqlalchemy.orm import Session, sessionmaker
from tests.support.admin_services import PASSWORD
from tests.support.housing_services import provision_housing

from backend_app.core.admin_sessions import AdminSessionStore
from backend_app.core.errors import AppError
from backend_app.core.identifiers import new_id
from backend_app.domain.admin.types import AdminScope
from backend_app.schemas.admin import AdminLogin, ProfileUpdate
from backend_app.services.platform_admin.admin import PlatformAdminService
from backend_app.services.property_admin.admin import PropertyAdminService


@pytest.fixture
def session_stores(
    real_admin: tuple[sessionmaker[Session], AdminSessionStore],
) -> tuple[AdminSessionStore, AdminSessionStore]:
    _, original = real_admin
    settings = original.settings.model_copy(update={"admin_login_limit": 1})
    return (
        AdminSessionStore(original.client, settings),
        AdminSessionStore(original.client, settings, key_prefix=REDIS_KEY_PREFIX),
    )


@pytest.mark.parametrize("scope", ["platform_admin", "property_admin"])
def test_session_reads_touch_and_delete_are_isolated_even_with_equal_tokens(
    session_stores: tuple[AdminSessionStore, AdminSessionStore],
    monkeypatch: pytest.MonkeyPatch,
    scope: AdminScope,
) -> None:
    normal, seed = session_stores
    token = secrets.token_urlsafe(32)
    monkeypatch.setattr("backend_app.core.session_store.secrets.token_urlsafe", lambda _: token)
    normal_id, seed_id = new_id(), new_id()
    normal.create(scope, normal_id, 1)
    _, stored = seed.create(scope, seed_id, 1)
    normal_record, seed_record = normal.read(scope, token), seed.read(scope, token)
    assert normal_record is not None and normal_record[0] == normal_id
    assert seed_record is not None and seed_record[0] == seed_id
    normal_key = next(normal.client.scan_iter(match=f"app:session:{scope}:*"))
    seed_key = next(normal.client.scan_iter(match=f"app:seed:session:{scope}:*"))
    normal.client.expire(normal_key, 10)
    normal.client.expire(seed_key, 1)
    seed.touch(scope, token, stored)
    assert 0 < normal.client.ttl(normal_key) <= 10
    assert normal.client.ttl(seed_key) > 10
    seed.delete(scope, token)
    assert seed.read(scope, token) is None
    assert normal.read(scope, token) is not None
    with pytest.raises(AppError) as caught:
        seed.touch(scope, token, stored)
    assert caught.value.code == "auth.unauthenticated"
    assert not normal.client.exists(seed_key)
    normal.touch(scope, token, normal_record[1])
    normal.delete(scope, token)
    assert normal.read(scope, token) is None


@pytest.mark.parametrize("scope", ["platform_admin", "property_admin"])
@pytest.mark.parametrize("limited_store", ["normal", "seed"])
@pytest.mark.parametrize("dimension", ["account", "ip"])
def test_each_rate_limit_is_enforced_only_inside_its_namespace(
    session_stores: tuple[AdminSessionStore, AdminSessionStore],
    scope: AdminScope,
    limited_store: str,
    dimension: str,
) -> None:
    normal, seed = session_stores
    exhausted, other = (normal, seed) if limited_store == "normal" else (seed, normal)
    exhausted.limit_login(scope, "MixedCase", "first-source")
    login, source = (
        ("mixedcase", "second-source")
        if dimension == "account"
        else ("another-account", "first-source")
    )
    with pytest.raises(AppError) as caught:
        exhausted.limit_login(scope, login, source)
    assert caught.value.code == "auth.rate_limited"
    other.limit_login(scope, login, source)
    with pytest.raises(AppError) as caught:
        other.limit_login(scope, login, source)
    assert caught.value.code == "auth.rate_limited"
    # Both Lua KEYS must be namespaced and retain their expiry.
    for prefix in ("app", "app:seed"):
        for kind in ("account", "ip"):
            keys = list(normal.client.scan_iter(match=f"{prefix}:admin-login:{scope}:{kind}:*"))
            assert keys
            assert all(
                0 < normal.client.ttl(key) <= normal.settings.admin_login_window_seconds
                for key in keys
            )


@pytest.mark.parametrize("scope", ["platform_admin", "property_admin"])
def test_seed_authentication_uses_existing_services_with_independent_sessions_and_limits(
    real_admin: tuple[sessionmaker[Session], AdminSessionStore],
    scope: AdminScope,
) -> None:
    factory, original = real_admin
    settings = original.settings.model_copy(update={"admin_login_limit": 1})
    normal = AdminSessionStore(original.client, settings)
    seed = AdminSessionStore(original.client, settings, key_prefix=REDIS_KEY_PREFIX)
    provision_housing(factory, normal)
    login = "root" if scope == "platform_admin" else "housing"
    actor = Actor(scope, login, PASSWORD, secrets.token_hex(12))
    with factory() as db:
        service = (
            PlatformAdminService(db) if scope == "platform_admin" else PropertyAdminService(db)
        )
        normal_token, _ = service.login(
            AdminLogin(login_name=login, password=PASSWORD),
            normal,
            "seed-cli:" + login,
            "normal-login",
        )
        with pytest.raises(AppError) as caught:
            service.login(
                AdminLogin(login_name=login, password=PASSWORD),
                normal,
                "seed-cli:" + login,
                "normal-limited",
            )
        assert caught.value.code == "auth.rate_limited"
        context = actor.get(db, seed)
        assert actor.token is not None
        with pytest.raises(AppError) as caught:
            service.authenticate(normal, actor.token)
        assert caught.value.code == "auth.unauthenticated"
        with pytest.raises(AppError) as caught:
            actor.service(db).authenticate(seed, normal_token)
        assert caught.value.code == "auth.unauthenticated"
        profile = actor.service(db).update_profile(
            context,
            ProfileUpdate(display_name="Seed authenticated operator"),
            "seed-profile",
        )
        assert profile.display_name == "Seed authenticated operator"
        assert service.authenticate(normal, normal_token).account_id == context.account_id
        actor.close(seed)
        assert normal.read(scope, normal_token) is not None
