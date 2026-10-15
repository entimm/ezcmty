from typing import Any
from uuid import UUID

import pytest
from tests.support.admin import Harness, admin, company
from tests.support.workspace import create_community


@pytest.fixture
def company_record(harness: Harness) -> dict[str, Any]:
    harness.login()
    return company(harness)


@pytest.fixture
def community_record(harness: Harness, company_record: dict[str, Any]) -> dict[str, Any]:
    renamed = harness.client.patch(
        f"/v1/property-companies/{company_record['id']}",
        json={"name": "新公司"},
        headers=harness.headers(),
    )
    assert renamed.status_code == 200
    return create_community(harness, company_record["id"], "community")


def test_company_defaults(company_record: dict[str, Any]) -> None:
    assert not company_record["enabled"]
    assert company_record["created_at"] == company_record["updated_at"]
    assert UUID(company_record["id"]).version == 7
    assert company_record["created_at"].endswith("Z")


def test_company_activation_requires_admin(
    harness: Harness, company_record: dict[str, Any]
) -> None:
    response = harness.client.patch(
        f"/v1/property-companies/{company_record['id']}",
        json={"enabled": True},
        headers=harness.headers(),
    )
    assert response.status_code == 409
    assert response.json()["code"] == "property.company_admin_required"


def test_provisioned_admin_defaults(harness: Harness, company_record: dict[str, Any]) -> None:
    account = admin(harness, company_record["id"])
    assert account["scope"] == "property_admin"
    assert account["property_company_id"] == company_record["id"]
    assert account["enabled"] and account["must_change_password"]
    assert account["roles"][0]["code"] == "super_admin" and account["roles"][0]["is_system"]


def test_company_with_admin_can_activate_without_communities(
    harness: Harness, company_record: dict[str, Any]
) -> None:
    admin(harness, company_record["id"])
    response = harness.client.patch(
        f"/v1/property-companies/{company_record['id']}",
        json={"enabled": True},
        headers=harness.headers(),
    )
    assert response.status_code == 200


def test_company_update_can_clear_contact(harness: Harness, company_record: dict[str, Any]) -> None:
    response = harness.client.patch(
        f"/v1/property-companies/{company_record['id']}",
        json={"name": "新公司", "contact_name": None},
        headers=harness.headers(),
    )
    assert response.status_code == 200 and response.json()["contact_name"] is None
    assert response.json()["updated_at"] > company_record["updated_at"]


@pytest.mark.parametrize(
    "payload",
    [{"code": "changed"}, {"scope": "property_admin"}, {"name": "   "}],
    ids=["immutable-code", "forged-scope", "blank-name"],
)
def test_company_update_rejects_invalid_fields(
    harness: Harness, company_record: dict[str, Any], payload: dict[str, str]
) -> None:
    response = harness.client.patch(
        f"/v1/property-companies/{company_record['id']}",
        json=payload,
        headers=harness.headers(),
    )
    assert response.status_code == 422


def test_company_code_is_unique(harness: Harness, company_record: dict[str, Any]) -> None:
    response = harness.client.post(
        "/v1/property-companies",
        json={"code": company_record["code"], "name": "重复"},
        headers=harness.headers(),
    )
    assert response.status_code == 409
    assert response.json()["code"] == "property.duplicate_company_code"


def test_community_defaults_include_company_name(community_record: dict[str, Any]) -> None:
    assert community_record["enabled"]
    assert community_record["property_company_name"] == "新公司"


@pytest.mark.parametrize("field", ["code", "property_company_id"])
def test_community_identity_is_immutable(
    harness: Harness, community_record: dict[str, Any], field: str
) -> None:
    value = "changed" if field == "code" else community_record["property_company_id"]
    response = harness.client.patch(
        f"/v1/communities/{community_record['id']}",
        json={field: value},
        headers=harness.headers(),
    )
    assert response.status_code == 422


def test_community_update_is_persisted(harness: Harness, community_record: dict[str, Any]) -> None:
    path = f"/v1/communities/{community_record['id']}"
    updated = harness.client.patch(
        path, json={"enabled": False, "address": "新地址"}, headers=harness.headers()
    )
    assert updated.status_code == 200
    assert harness.client.get(path).json()["address"] == "新地址"


def test_community_code_is_unique(harness: Harness, community_record: dict[str, Any]) -> None:
    response = harness.client.post(
        "/v1/communities",
        json={
            "property_company_id": community_record["property_company_id"],
            "code": community_record["code"],
            "name": "重复",
            "address": "街道 1 号",
        },
        headers=harness.headers(),
    )
    assert response.status_code == 409
    assert response.json()["code"] == "property.duplicate_community_code"


def test_community_list_filters_company_and_status(
    harness: Harness, community_record: dict[str, Any]
) -> None:
    updated = harness.client.patch(
        f"/v1/communities/{community_record['id']}",
        json={"enabled": False},
        headers=harness.headers(),
    )
    assert updated.status_code == 200
    response = harness.client.get(
        "/v1/communities",
        params={"property_company_id": community_record["property_company_id"], "enabled": False},
    )
    assert response.json()["total"] == 1


def test_company_list_combines_filters(harness: Harness, company_record: dict[str, Any]) -> None:
    admin(harness, company_record["id"])
    updated = harness.client.patch(
        f"/v1/property-companies/{company_record['id']}",
        json={"name": "新公司", "enabled": True},
        headers=harness.headers(),
    )
    assert updated.status_code == 200
    response = harness.client.get(
        "/v1/property-companies",
        params={"name": "新", "code": "comp", "enabled": True, "page_size": 1},
    )
    assert response.json()["total"] == 1
