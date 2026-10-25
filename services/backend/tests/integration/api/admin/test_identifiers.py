from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select, text
from tests.support.admin import TEST_PASSWORD, Harness

from backend_app.core.admin_security import hash_password
from backend_app.models.admin import (
    AdminAccount,
    AdminAccountRole,
    AdminAuditLog,
    AdminRole,
    AdminRolePermission,
)


def test_uuidv7_native_storage_and_creation_times(harness: Harness) -> None:
    session = harness.login()
    assert UUID(session["subject_id"]).version == 7
    headers = harness.headers()
    role = harness.client.post(
        "/v1/admin-roles", json={"code": "uuid_reader", "name": "UUID 读者"}, headers=headers
    )
    assert role.status_code == 201
    permissions = harness.client.put(
        f"/v1/admin-roles/{role.json()['id']}/permissions",
        json={"permissions": ["platform.system.read"]},
        headers=headers,
    )
    assert permissions.status_code == 200
    with harness.factory() as db:
        for model in (AdminAccount, AdminRole, AdminAuditLog):
            rows: Sequence[UUID] = (
                db.execute(text(f"SELECT id FROM {model.__tablename__}")).scalars().all()
            )
            assert rows
            for stored in rows:
                assert isinstance(stored, UUID)
                identifier = stored
                assert identifier.version == 7
                entity = db.get(model, str(identifier))
                assert isinstance(entity, AdminAccount | AdminRole | AdminAuditLog)
                assert entity.id == str(identifier)
        now = datetime.now(UTC)
        for record_model in (
            AdminAccount,
            AdminRole,
            AdminAccountRole,
            AdminRolePermission,
            AdminAuditLog,
        ):
            created_times = db.scalars(select(record_model.created_at)).all()
            assert created_times
            assert all(value.tzinfo is not None and value <= now for value in created_times)
        links = db.execute(text("SELECT account_id, role_id FROM admin_account_roles")).all()
        assert all(isinstance(value, UUID) for row in links for value in row)
    response = harness.client.get(f"/v1/admin-accounts/{session['subject_id'].upper()}")
    assert response.status_code == 200 and response.json()["id"] == session["subject_id"]
    audits = harness.client.get("/v1/admin-audit-logs").json()["items"]
    for entry in audits:
        for name in ("id", "actor_id", "target_id"):
            if entry[name] is not None:
                assert str(UUID(entry[name])) == entry[name]


def test_uuid_v4_identifiers_remain_stable_and_are_normalized(harness: Harness) -> None:
    harness.login()
    account_id, role_id = str(uuid4()), str(uuid4())
    with harness.factory() as db:
        db.add_all(
            [
                AdminAccount(
                    id=account_id,
                    scope="platform_admin",
                    login_name="legacy",
                    display_name="存量账号",
                    password_hash=hash_password(TEST_PASSWORD),
                    must_change_password=False,
                ),
                AdminRole(id=role_id, scope="platform_admin", code="legacy", name="存量角色"),
            ]
        )
        db.commit()
    response = harness.client.put(
        f"/v1/admin-accounts/{account_id.upper()}/roles",
        json={"role_ids": [role_id.upper()]},
        headers=harness.headers(),
    )
    assert response.status_code == 200
    assert response.json()["id"] == account_id
    assert response.json()["roles"][0]["id"] == role_id
    with harness.factory() as db:
        raw: UUID = db.execute(
            text("SELECT id FROM admin_accounts WHERE login_name = 'legacy'")
        ).scalar_one()
        assert raw == UUID(account_id)
        link = db.scalar(select(AdminAccountRole).where(AdminAccountRole.account_id == account_id))
        assert link is not None and link.account_id == account_id and link.role_id == role_id
    assert harness.login(name="legacy", password=TEST_PASSWORD)["subject_id"] == account_id
    assert harness.client.get("/v1/admin-accounts/me").json()["id"] == account_id


def test_invalid_uuid_identifiers_return_validation_errors(harness: Harness) -> None:
    session = harness.login()
    identifier = session["subject_id"]
    invalid_ids = (
        "not-a-uuid",
        identifier.replace("-", ""),
        "{" + identifier + "}",
        "00000000-0000-0000-0000-000000000000",
        "00000000-0000-1000-8000-000000000000",
        "00000000-0000-7000-0000-000000000000",
    )
    headers = harness.headers()
    for value in invalid_ids:
        for resource in ("admin-accounts", "admin-roles"):
            response = harness.client.get(f"/v1/{resource}/{value}")
            assert response.status_code == 422, response.text
            assert response.json()["code"] == "VALIDATION_ERROR"
        response = harness.client.put(
            f"/v1/admin-accounts/{identifier}/roles", json={"role_ids": [value]}, headers=headers
        )
        assert response.status_code == 422 and response.json()["code"] == "VALIDATION_ERROR"
    missing = harness.client.get(f"/v1/admin-accounts/{uuid4()}")
    assert missing.status_code == 404 and missing.json()["code"] == "resource.not_found"
