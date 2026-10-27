from typing import Any

import pytest
from sqlalchemy import func, select
from tests.support.admin import Harness
from tests.support.resident import ResidentHarness

from backend_app.models.miniapp import MiniappUser, PhoneBinding, PhoneVerification


def test_login_reuses_wechat_account_and_sessions_are_isolated(
    resident: ResidentHarness, harness: Harness
) -> None:
    first_id = resident.user_id
    resident.login()
    assert resident.user_id == first_id
    with harness.factory() as db:
        assert db.scalar(select(func.count()).select_from(MiniappUser)) == 1
    response = resident.client.get("/v1/miniapp-users/me", headers=resident.headers())
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert "wechat_openid" not in response.json()
    assert (
        resident.client.get("/v1/admin-accounts/me", headers=resident.headers()).status_code == 404
    )
    assert (
        harness.client.get("/v1/admin-accounts/me", headers=resident.headers()).status_code == 401
    )
    assert (
        resident.client.delete(
            "/v1/client-sessions/current", headers=resident.headers()
        ).status_code
        == 204
    )
    assert (
        resident.client.get("/v1/miniapp-users/me", headers=resident.headers()).status_code == 401
    )


def test_multiple_phones_unbind_and_replay_do_not_reactivate(
    resident: ResidentHarness, harness: Harness
) -> None:
    first = resident.phone()
    second = resident.phone("13900139000")
    assert first["id"] != second["id"]
    response = resident.client.delete(
        f"/v1/miniapp-users/me/phone-bindings/{first['id']}",
        params={"expected_row_version": first["row_version"]},
        headers=resident.headers(),
    )
    assert response.status_code == 204, response.text
    replay = resident.client.post(
        "/v1/miniapp-users/me/phone-bindings",
        json={"code": "phone-1"},
        headers=resident.headers("phone-1"),
    )
    assert replay.status_code == 201
    assert replay.json()["status"] == "unbound"
    assert len(resident.wechat.exchanges) == 2
    rebound = resident.phone()
    assert rebound["id"] == first["id"] and rebound["status"] == "active"
    with harness.factory() as db:
        assert db.scalar(select(func.count()).select_from(PhoneBinding)) == 2
        assert db.scalar(select(func.count()).select_from(PhoneVerification)) == 3
    assert not any(
        "13800138000" in value[0] or "phone-1" in value[0]
        for value in harness.redis.values.values()
    )


def test_phone_manual_mismatch_creates_no_records(
    resident: ResidentHarness, harness: Harness
) -> None:
    resident.wechat.phones["manual"] = "13800138000"
    response = resident.client.post(
        "/v1/miniapp-users/me/phone-bindings",
        json={"code": "manual", "expected_phone": "+8613900139000"},
        headers=resident.headers("manual"),
    )
    assert response.status_code == 409
    assert response.json()["code"] == "wechat.phone_mismatch"
    with harness.factory() as db:
        assert db.scalar(select(func.count()).select_from(PhoneVerification)) == 0
        assert db.scalar(select(func.count()).select_from(PhoneBinding)) == 0


def test_phone_is_never_shared_between_accounts(resident: ResidentHarness) -> None:
    first = resident.phone()
    resident.login("another-user")
    response = resident.client.delete(
        f"/v1/miniapp-users/me/phone-bindings/{first['id']}",
        params={"expected_row_version": 1},
        headers=resident.headers(),
    )
    assert response.status_code == 404
    second = resident.phone()
    assert first["id"] != second["id"] and first["phone"] == second["phone"]


def test_committed_phone_verification_survives_unknown_result(
    resident: ResidentHarness, harness: Harness
) -> None:
    first = resident.phone()
    resident.wechat.phones["different"] = "13900139000"
    conflict = resident.client.post(
        "/v1/miniapp-users/me/phone-bindings",
        json={"code": "different"},
        headers=resident.headers("phone-1"),
    )
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "resident.idempotency_conflict"
    assert len(resident.wechat.exchanges) == 1
    assert first["status"] == "active"


def test_phone_write_failure_rolls_back_verification_and_requires_new_auth(
    resident: ResidentHarness, harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy.orm import Session

    original = Session.commit

    def fail_commit(db: Session) -> None:
        raise RuntimeError("injected database failure")

    resident.wechat.phones["consumed"] = "13800138000"
    with monkeypatch.context() as patch:
        patch.setattr(Session, "commit", fail_commit)
        response = resident.client.post(
            "/v1/miniapp-users/me/phone-bindings",
            json={"code": "consumed"},
            headers=resident.headers("failed"),
        )
        assert response.status_code == 500
    assert Session.commit is original
    with harness.factory() as db:
        assert db.scalar(select(func.count()).select_from(PhoneBinding)) == 0
        assert db.scalar(select(func.count()).select_from(PhoneVerification)) == 0
    response = resident.client.post(
        "/v1/miniapp-users/me/phone-bindings",
        json={"code": "consumed"},
        headers=resident.headers("failed"),
    )
    assert response.status_code == 422
    assert resident.phone()["status"] == "active"


@pytest.mark.parametrize(
    "field,value",
    [("wechat_appid", "client-app"), ("user_id", "client-user"), ("phone", "13800138000")],
)
def test_phone_api_rejects_client_identity_and_phone_fields(
    resident: ResidentHarness, field: str, value: Any
) -> None:
    response = resident.client.post(
        "/v1/miniapp-users/me/phone-bindings",
        json={"code": "code", field: value},
        headers=resident.headers("bad"),
    )
    assert response.status_code == 422
