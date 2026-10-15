import pytest
from tests.support.admin import TEST_PASSWORD, Harness, company

from backend_app.schemas.admin import AdminLogin
from backend_app.services.property_admin.admin import PropertyAdminService


@pytest.mark.parametrize("kind", ["company", "community"])
def test_organization_codes_are_canonical_unique_and_searchable(
    harness: Harness, kind: str
) -> None:
    harness.login()
    owner = company(harness, "owner")
    path = "/v1/property-companies" if kind == "company" else "/v1/communities"
    payload = {"code": "aBc-01", "name": "Mixed_Name%"}
    if kind == "community":
        payload.update(property_company_id=owner["id"], address="地址")
    created = harness.client.post(path, json=payload, headers=harness.headers())
    assert created.status_code == 201, created.text
    assert created.json()["code"] == "ABC-01"
    duplicate = harness.client.post(
        path,
        json={**payload, "code": "AbC-01"},
        headers=harness.headers(),
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == f"property.duplicate_{kind}_code"
    listing = harness.client.get(path, params={"code": "aBc"}).json()
    assert listing["total"] == 1 and listing["items"][0]["id"] == created.json()["id"]
    by_name = harness.client.get(path, params={"name": "mixed_name%"}).json()
    assert by_name["total"] == 1 and by_name["items"][0]["name"] == "Mixed_Name%"
    # Literal underscores and percent signs must not match ordinary letters.
    other = {**payload, "code": "other", "name": "MixedXNameSuffix"}
    assert harness.client.post(path, json=other, headers=harness.headers()).status_code == 201
    assert harness.client.get(path, params={"name": "mixed_name%"}).json()["total"] == 1
    empty_page = harness.client.get(path, params={"code": "abc", "page": 100}).json()
    assert empty_page["items"] == [] and empty_page["total"] == 1


def test_property_account_creation_and_login_use_lowercase_name(harness: Harness) -> None:
    harness.login()
    owner = company(harness)
    path = f"/v1/property-companies/{owner['id']}/admin-accounts"
    payload = {"login_name": "Property.Admin", "display_name": "物业", "password": TEST_PASSWORD}
    created = harness.client.post(path, json=payload, headers=harness.headers())
    assert created.status_code == 201 and created.json()["login_name"] == "property.admin"
    duplicate = harness.client.post(
        path,
        json={**payload, "login_name": "PROPERTY.ADMIN"},
        headers=harness.headers(),
    )
    assert duplicate.status_code == 409 and duplicate.json()["code"] == "admin.duplicate_login"
    listing = harness.client.get(path, params={"login_name": "PROPERTY."}).json()
    assert listing["total"] == 1 and listing["items"][0]["login_name"] == "property.admin"
    enabled = harness.client.patch(
        f"/v1/property-companies/{owner['id']}",
        json={"enabled": True},
        headers=harness.headers(),
    )
    assert enabled.status_code == 200
    with harness.factory() as db:
        _, session = PropertyAdminService(db).login(
            AdminLogin(login_name="pRoPeRtY.AdMiN", password=TEST_PASSWORD),
            harness.store,
            "property-ip",
            "normalized-property-login",
        )
        assert session.login_name == "property.admin" and session.subject_id == created.json()["id"]
