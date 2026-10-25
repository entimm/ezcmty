from __future__ import annotations

from typing import Any

from tests.support.admin import NEW_PASSWORD, TEST_PASSWORD, Harness, admin, company

from backend_app.models.admin import AdminAccount
from backend_app.repositories.admin import AdminRepository


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


def test_operator_business_permissions_do_not_grant_company_admin_writes(harness: Harness) -> None:
    harness.login()
    c = company(harness)
    headers = harness.headers()
    role = harness.client.post(
        "/v1/admin-roles", json={"code": "operator", "name": "运营"}, headers=headers
    ).json()
    permissions = [
        "platform.onboarding.read",
        "platform.onboarding.manage",
        "platform.onboarding.manage",
        "platform.onboarding.read",
        "platform.onboarding.manage",
        "platform.onboarding.manage",
        "platform.system.read",
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
        json={"permissions": ["platform.system.manage"]},
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
