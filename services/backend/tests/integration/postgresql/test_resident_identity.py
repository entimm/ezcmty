from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker
from tests.support.resident import FakeWechat

from backend_app.core import resident_sessions
from backend_app.core.admin_sessions import AdminSessionStore
from backend_app.core.errors import AppError
from backend_app.core.identifiers import new_id
from backend_app.core.resident_sessions import ResidentSessionStore
from backend_app.integrations.wechat_miniapp import VerifiedPhone
from backend_app.models.miniapp import MiniappUser, PhoneBinding, PhoneVerification
from backend_app.schemas.miniapp import MiniappLogin, PhoneBindingCreate
from backend_app.services.resident.identity import ResidentIdentityService


def test_concurrent_first_login_creates_one_user_and_independent_sessions(
    real_admin: tuple[sessionmaker[Session], AdminSessionStore],
) -> None:
    factory, admin = real_admin
    store = ResidentSessionStore(admin.client, admin.settings)
    barrier = Barrier(2)

    class SimultaneousWechat(FakeWechat):
        def login(self, code: str) -> str:
            barrier.wait(timeout=10)
            return "same-platform-openid"

    def login(code: str) -> tuple[str, str]:
        with factory() as db:
            result = ResidentIdentityService(db).login(
                MiniappLogin(code=code), store, SimultaneousWechat(), "same-source"
            )
            return result.user.id, result.token

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(login, code) for code in ("first-code", "second-code")]
        results = [future.result(timeout=15) for future in futures]
    assert results[0][0] == results[1][0]
    assert results[0][1] != results[1][1]
    assert all(store.authenticate(token).user_id == results[0][0] for _, token in results)
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(MiniappUser)) == 1
        assert db.scalar(select(func.count()).select_from(PhoneBinding)) == 0


def test_real_resident_session_scope_absolute_lifetime_and_logout(
    real_admin: tuple[sessionmaker[Session], AdminSessionStore],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, admin = real_admin
    now = 1000.0
    monkeypatch.setattr(resident_sessions, "time", lambda: now)
    settings = admin.settings.model_copy(
        update={"resident_session_idle_seconds": 60, "resident_session_absolute_seconds": 120}
    )
    store = ResidentSessionStore(admin.client, settings)
    user_id = new_id()
    token, _ = store.create(user_id, 2)
    assert store.authenticate(token).version == 2
    assert admin.read("property_admin", token) is None
    assert admin.read("platform_admin", token) is None
    admin_token, _ = admin.create("property_admin", new_id(), 1)
    with pytest.raises(AppError) as foreign_session:
        store.authenticate(admin_token)
    assert foreign_session.value.code == "auth.unauthenticated"
    now += 115
    assert store.authenticate(token).user_id == user_id
    key = store.store._key("resident", token)
    assert 0 < admin.client.ttl(key) <= 5
    assert token not in key and token not in (admin.client.get(key) or "")
    now += 6
    with pytest.raises(AppError) as expired:
        store.authenticate(token)
    assert expired.value.code == "auth.unauthenticated"
    another, _ = store.create(user_id, 2)
    store.delete(another)
    with pytest.raises(AppError) as logged_out:
        store.authenticate(another)
    assert logged_out.value.code == "auth.unauthenticated"


def test_real_resident_rate_counter_is_atomic_and_returns_remaining_window(
    real_admin: tuple[sessionmaker[Session], AdminSessionStore],
) -> None:
    _, admin = real_admin
    store = ResidentSessionStore(admin.client, admin.settings)
    barrier = Barrier(4)

    def limited_request() -> int:
        barrier.wait(timeout=10)
        try:
            store.limit("phone", "same-user", 2)
            return 0
        except AppError as error:
            assert error.code == "resident.rate_limited" and error.status_code == 429
            assert (
                error.retry_after
                and 0 < error.retry_after <= admin.settings.resident_rate_window_seconds
            )
            return error.retry_after

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(limited_request) for _ in range(4)]
        results = [future.result(timeout=15) for future in futures]
    assert results.count(0) == 2
    assert len([result for result in results if result > 0]) == 2


def test_real_phone_lock_prevents_duplicate_exchange_and_replays_durable_result(
    real_admin: tuple[sessionmaker[Session], AdminSessionStore],
) -> None:
    factory, admin = real_admin
    store = ResidentSessionStore(admin.client, admin.settings)
    entered, release = Event(), Event()

    class HeldWechat(FakeWechat):
        def verify_phone(self, code: str, openid: str) -> VerifiedPhone:
            entered.set()
            assert release.wait(10), "Phone exchange was not released"
            return super().verify_phone(code, openid)

    wechat = HeldWechat()
    wechat.phones["one-use-phone-code"] = "13800138000"
    with factory() as db:
        result = ResidentIdentityService(db).login(
            MiniappLogin(code="resident"), store, wechat, "source"
        )
    ctx = store.authenticate(result.token)
    data = PhoneBindingCreate(code="one-use-phone-code")

    def bind() -> str:
        with factory() as db:
            return (
                ResidentIdentityService(db)
                .bind_phone(ctx, data, "phone-key", "request", store, wechat)
                .id
            )

    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(bind)
        try:
            assert entered.wait(10)
            with pytest.raises(AppError) as conflict:
                bind()
            assert conflict.value.code == "resident.state_changed"
        finally:
            release.set()
        binding_id = first.result(timeout=10)
    assert bind() == binding_id
    assert len(wechat.exchanges) == 1
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(PhoneBinding)) == 1
        assert db.scalar(select(func.count()).select_from(PhoneVerification)) == 1
    for key in admin.client.scan_iter():
        value = admin.client.get(key) or ""
        assert "one-use-phone-code" not in key + value
        assert "13800138000" not in key + value
