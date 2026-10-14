from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import pytest
from pytest import MonkeyPatch
from sqlalchemy import func, select

from backend_app.core.errors import AppError
from backend_app.models.admin import AdminAccount, AdminAccountRole, AdminAuditLog, AdminRole
from backend_app.models.property import PropertyCompany
from backend_app.repositories.admin import AdminRepository
from backend_app.schemas import admin as schema
from backend_app.services.admin import AdminService
from tests.unit.test_admin import NEW_PASSWORD, TEST_PASSWORD, Harness
from tests.unit.test_admin import harness as harness


def company(h: Harness, code: str = "company") -> dict[str, Any]:
    response = h.client.post(
        "/v1/property-companies",
        json={"code": code, "name": code, "contact_name": "联系人"},
        headers=h.headers(),
    )
    assert response.status_code == 201, response.text
    return dict(response.json())


def admin(h: Harness, company_id: str, name: str = "property_root") -> dict[str, Any]:
    response = h.client.post(
        f"/v1/property-companies/{company_id}/admin-accounts",
        json={"login_name": name, "display_name": name, "password": TEST_PASSWORD},
        headers=h.headers(),
    )
    assert response.status_code == 201, response.text
    return dict(response.json())


def test_onboarding_defaults_validation_and_immutable_fields(harness: Harness) -> None:
    harness.login()
    headers = harness.headers()
    c = company(harness)
    path = f"/v1/property-companies/{c['id']}"
    assert not c["enabled"] and c["created_at"] == c["updated_at"]
    assert UUID(c["id"]).version == 7 and c["created_at"].endswith("Z")
    response = harness.client.patch(path, json={"enabled": True}, headers=headers)
    assert (
        response.status_code == 409 and response.json()["code"] == "property.company_admin_required"
    )
    a = admin(harness, c["id"])
    assert a["scope"] == "property_admin" and a["property_company_id"] == c["id"]
    assert a["enabled"] and a["must_change_password"]
    assert a["roles"][0]["code"] == "super_admin" and a["roles"][0]["is_system"]
    # Communities are optional for activation.
    assert harness.client.patch(path, json={"enabled": True}, headers=headers).status_code == 200
    updated = harness.client.patch(
        path, json={"name": "新公司", "contact_name": None}, headers=headers
    )
    assert updated.status_code == 200 and updated.json()["contact_name"] is None
    assert updated.json()["updated_at"] > c["updated_at"]
    for payload in ({"code": "changed"}, {"scope": "property_admin"}, {"name": "   "}):
        assert harness.client.patch(path, json=payload, headers=headers).status_code == 422
    duplicate = harness.client.post(
        "/v1/property-companies", json={"code": c["code"], "name": "重复"}, headers=headers
    )
    assert (
        duplicate.status_code == 409
        and duplicate.json()["code"] == "property.duplicate_company_code"
    )
    community_data = {
        "property_company_id": c["id"],
        "code": "community",
        "name": "小区",
        "address": "街道 1 号",
    }
    response = harness.client.post("/v1/communities", json=community_data, headers=headers)
    assert response.status_code == 201, response.text
    community = response.json()
    assert community["enabled"] and community["property_company_name"] == "新公司"
    community_path = f"/v1/communities/{community['id']}"
    for payload in ({"code": "changed"}, {"property_company_id": c["id"]}):
        assert (
            harness.client.patch(community_path, json=payload, headers=headers).status_code == 422
        )
    assert (
        harness.client.patch(
            community_path, json={"enabled": False, "address": "新地址"}, headers=headers
        ).status_code
        == 200
    )
    assert harness.client.get(community_path).json()["address"] == "新地址"
    duplicate = harness.client.post("/v1/communities", json=community_data, headers=headers)
    assert (
        duplicate.status_code == 409
        and duplicate.json()["code"] == "property.duplicate_community_code"
    )
    assert (
        harness.client.get(f"/v1/communities?property_company_id={c['id']}&enabled=false").json()[
            "total"
        ]
        == 1
    )
    assert (
        harness.client.get(
            "/v1/property-companies?name=新&code=comp&enabled=true&page_size=1"
        ).json()["total"]
        == 1
    )


def test_nested_admin_range_and_scope_cannot_be_chosen(harness: Harness) -> None:
    identity = harness.login()
    headers = harness.headers()
    first, second = company(harness, "first"), company(harness, "second")
    a = admin(harness, first["id"])
    b = admin(harness, second["id"], "other")
    invalid_inputs: list[dict[str, Any]] = [
        {"scope": "platform_admin"},
        {"property_company_id": second["id"]},
        {"role_ids": []},
        {"community_ids": []},
    ]
    for invalid in invalid_inputs:
        response = harness.client.post(
            f"/v1/property-companies/{first['id']}/admin-accounts",
            json={
                "login_name": "injected",
                "display_name": "注入",
                "password": TEST_PASSWORD,
                **invalid,
            },
            headers=headers,
        )
        assert response.status_code == 422
    duplicate = harness.client.post(
        f"/v1/property-companies/{second['id']}/admin-accounts",
        json={"login_name": a["login_name"], "display_name": "重复", "password": TEST_PASSWORD},
        headers=headers,
    )
    assert duplicate.status_code == 409 and duplicate.json()["code"] == "admin.duplicate_login"
    for target in (b["id"], identity["subject_id"]):
        path = f"/v1/property-companies/{first['id']}/admin-accounts/{target}"
        assert harness.client.get(path).status_code == 404
        assert (
            harness.client.patch(path, json={"enabled": False}, headers=headers).status_code == 404
        )
        assert (
            harness.client.post(
                path + "/password-resets", json={"password": NEW_PASSWORD}, headers=headers
            ).status_code
            == 404
        )
    items = harness.client.get(f"/v1/property-companies/{first['id']}/admin-accounts").json()[
        "items"
    ]
    assert [item["id"] for item in items] == [a["id"]]
    assert harness.client.get(f"/v1/admin-accounts/{a['id']}").status_code == 404
    for payload in ({"login_name": "changed"}, {"property_company_id": second["id"]}):
        response = harness.client.patch(
            f"/v1/property-companies/{first['id']}/admin-accounts/{a['id']}",
            json=payload,
            headers=headers,
        )
        assert response.status_code == 422
    with harness.factory() as db:
        unbound = AdminRepository(db, "property_admin")
        bound = AdminRepository(db, "property_admin", first["id"])
        assert unbound.account(a["id"]) is None and unbound.role_by_code("super_admin") is None
        assert bound.account(b["id"]) is None and bound.role(b["roles"][0]["id"]) is None


def test_company_disabling_revokes_all_sessions_without_changing_child_status(
    harness: Harness,
) -> None:
    harness.login()
    c = company(harness)
    a, b = admin(harness, c["id"]), admin(harness, c["id"], "second")
    path = f"/v1/property-companies/{c['id']}"
    headers = harness.headers()
    with harness.factory() as db:
        svc = AdminService(db, "property_admin")
        with pytest.raises(AppError) as caught:
            svc.login(
                schema.AdminLogin(login_name=a["login_name"], password=TEST_PASSWORD),
                harness.store,
                "ip",
                "disabled-login",
            )
        assert caught.value.code == "auth.invalid_credentials"
    assert harness.client.patch(path, json={"enabled": True}, headers=headers).status_code == 200
    with harness.factory() as db:
        svc = AdminService(db, "property_admin")
        token, _ = svc.login(
            schema.AdminLogin(login_name=a["login_name"], password=TEST_PASSWORD),
            harness.store,
            "ip",
            "enabled-login",
        )
        ctx = svc.authenticate(harness.store, token)
        assert ctx.property_company_id == c["id"] and ctx.scope == "property_admin"
        versions = {
            row.id: row.session_version
            for row in db.scalars(
                select(AdminAccount).where(AdminAccount.property_company_id == c["id"])
            )
        }
    # Keep one enabled and one disabled account to check independent statuses.
    bpath = path + f"/admin-accounts/{b['id']}"
    assert harness.client.patch(bpath, json={"enabled": False}, headers=headers).status_code == 200
    with harness.factory() as db:
        account = db.get(AdminAccount, b["id"])
        assert account
        versions[b["id"]] = account.session_version
    assert harness.client.patch(path, json={"enabled": False}, headers=headers).status_code == 200
    assert harness.store.read("property_admin", token) is not None
    with harness.factory() as db:
        rows = list(
            db.scalars(select(AdminAccount).where(AdminAccount.property_company_id == c["id"]))
        )
        assert {row.id: row.enabled for row in rows} == {a["id"]: True, b["id"]: False}
        assert all(row.session_version == versions[row.id] + 1 for row in rows)
        with pytest.raises(AppError) as caught:
            AdminService(db, "property_admin").authenticate(harness.store, token)
        assert caught.value.code == "auth.unauthenticated"
    assert harness.client.patch(path, json={"enabled": True}, headers=headers).status_code == 200
    with harness.factory() as db:
        with pytest.raises(AppError) as caught:
            AdminService(db, "property_admin").authenticate(harness.store, token)
        assert caught.value.code == "auth.unauthenticated"
        new_token, _ = AdminService(db, "property_admin").login(
            schema.AdminLogin(login_name=a["login_name"], password=TEST_PASSWORD),
            harness.store,
            "ip",
            "reenabled-login",
        )
        assert new_token != token


def test_last_company_admin_and_password_reset_while_company_disabled(harness: Harness) -> None:
    harness.login()
    c = company(harness)
    a = admin(harness, c["id"])
    path = f"/v1/property-companies/{c['id']}/admin-accounts/{a['id']}"
    headers = harness.headers()
    protected = harness.client.patch(path, json={"enabled": False}, headers=headers)
    assert protected.status_code == 409 and protected.json()["code"] == "admin.last_super_admin"
    admin(harness, c["id"], "second")
    assert harness.client.patch(path, json={"enabled": False}, headers=headers).status_code == 200
    assert (
        harness.client.patch(
            path, json={"enabled": True, "display_name": "新名称"}, headers=headers
        ).status_code
        == 200
    )
    with harness.factory() as db:
        account = db.get(AdminAccount, a["id"])
        assert account
        account.must_change_password = False
        before = account.session_version
        db.commit()
    reset = harness.client.post(
        path + "/password-resets", json={"password": NEW_PASSWORD}, headers=headers
    )
    assert reset.status_code == 204
    with harness.factory() as db:
        account = db.get(AdminAccount, a["id"])
        assert account and account.session_version == before + 1 and account.must_change_password
        audits = list(
            db.scalars(select(AdminAuditLog).where(AdminAuditLog.action.like("property.%")))
        )
        assert audits and all(row.scope == "platform_admin" for row in audits)
        assert all(row.property_company_id == c["id"] for row in audits)
        assert all("property_company_id" not in row.safe_metadata for row in audits)
        assert TEST_PASSWORD not in json.dumps([row.safe_metadata for row in audits])
        assert NEW_PASSWORD not in json.dumps([row.safe_metadata for row in audits])
    public_audits = harness.client.get("/v1/admin-audit-logs").json()["items"]
    assert all(
        row["property_company_id"] == c["id"] and "property_company_id" not in row["metadata"]
        for row in public_audits
        if row["action"].startswith("property.")
    )


def test_operator_business_permissions_do_not_grant_company_admin_writes(harness: Harness) -> None:
    harness.login()
    c = company(harness)
    headers = harness.headers()
    role = harness.client.post(
        "/v1/admin-roles", json={"code": "operator", "name": "运营"}, headers=headers
    ).json()
    permissions = [
        "property.company.read",
        "property.company.create",
        "property.company.update",
        "property.community.read",
        "property.community.create",
        "property.community.update",
        "property.admin.read",
    ]
    assert (
        harness.client.put(
            f"/v1/admin-roles/{role['id']}/permissions",
            json={"permissions": permissions},
            headers=headers,
        ).status_code
        == 200
    )
    rejected = harness.client.put(
        f"/v1/admin-roles/{role['id']}/permissions",
        json={"permissions": ["property.admin.create"]},
        headers=headers,
    )
    assert rejected.status_code == 409 and rejected.json()["code"] == "admin.invalid_permission"
    result = harness.client.post(
        "/v1/admin-accounts",
        json={
            "login_name": "operator",
            "display_name": "运营",
            "password": TEST_PASSWORD,
            "role_ids": [role["id"]],
        },
        headers=headers,
    )
    assert result.status_code == 201
    with harness.factory() as db:
        account = db.get(AdminAccount, result.json()["id"])
        assert account
        account.must_change_password = False
        db.commit()
    harness.login("operator", TEST_PASSWORD)
    company(harness, "operator_company")
    assert harness.client.get(f"/v1/property-companies/{c['id']}/admin-accounts").status_code == 200
    response = harness.client.post(
        f"/v1/property-companies/{c['id']}/admin-accounts",
        json={"login_name": "forbidden", "display_name": "越权", "password": TEST_PASSWORD},
        headers=harness.headers(),
    )
    assert response.status_code == 403


def test_provision_and_company_disable_roll_back_when_audit_fails(
    harness: Harness, monkeypatch: MonkeyPatch
) -> None:
    harness.login()
    c = company(harness)
    original = AdminRepository.audit

    def fail(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("audit failure")

    monkeypatch.setattr(AdminRepository, "audit", fail)
    response = harness.client.post(
        f"/v1/property-companies/{c['id']}/admin-accounts",
        json={"login_name": "rollback", "display_name": "失败", "password": TEST_PASSWORD},
        headers=harness.headers(),
    )
    assert response.status_code == 500
    with harness.factory() as db:
        assert not db.scalar(
            select(func.count())
            .select_from(AdminRole)
            .where(AdminRole.property_company_id == c["id"])
        )
        assert not db.scalar(
            select(func.count())
            .select_from(AdminAccount)
            .where(AdminAccount.property_company_id == c["id"])
        )
        assert not db.scalar(
            select(func.count())
            .select_from(AdminAccountRole)
            .where(AdminAccountRole.property_company_id == c["id"])
        )
    monkeypatch.setattr(AdminRepository, "audit", original)
    a = admin(harness, c["id"])
    path = f"/v1/property-companies/{c['id']}"
    assert (
        harness.client.patch(path, json={"enabled": True}, headers=harness.headers()).status_code
        == 200
    )
    monkeypatch.setattr(AdminRepository, "audit", fail)
    response = harness.client.patch(path, json={"enabled": False}, headers=harness.headers())
    assert response.status_code == 500
    with harness.factory() as db:
        account, target = db.get(AdminAccount, a["id"]), db.get(PropertyCompany, c["id"])
        assert account and target and account.session_version == 1 and target.enabled


def test_property_runtime_exposes_no_onboarding_routes(harness: Harness) -> None:
    from backend_app.app_factory import create_app

    paths = create_app("property-admin-api").openapi()["paths"]
    assert "/v1/property-companies" not in paths
    assert "/v1/admin-sessions" in paths and "/v1/property-companies/current" in paths
    assert "/v1/admin-accounts" not in paths and "/v1/admin-audit-logs" not in paths
    assert set(paths["/v1/communities"]) == {"get"}
    assert set(paths["/v1/communities/{community_id}"]) == {"get"}
