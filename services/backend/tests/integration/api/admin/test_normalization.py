import pytest
from sqlalchemy import select
from tests.support.admin import ORIGIN, TEST_PASSWORD, Harness

from backend_app.models.admin import AdminAccount


@pytest.mark.parametrize("login_name", ["Mixed.Admin", "MIXED.ADMIN", "mixed.admin"])
def test_login_creation_matching_and_filtering_use_canonical_name(
    harness: Harness,
    login_name: str,
) -> None:
    harness.login()
    created = harness.client.post(
        "/v1/admin-accounts",
        json={"login_name": login_name, "display_name": "管理员", "password": TEST_PASSWORD},
        headers=harness.headers(),
    )
    assert created.status_code == 201, created.text
    assert created.json()["login_name"] == "mixed.admin"
    duplicate = harness.client.post(
        "/v1/admin-accounts",
        json={"login_name": "MiXeD.AdMiN", "display_name": "重复", "password": TEST_PASSWORD},
        headers=harness.headers(),
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "admin.duplicate_login"
    listing = harness.client.get("/v1/admin-accounts", params={"login_name": "MIXED."}).json()
    assert listing["total"] == 1 and listing["items"][0]["id"] == created.json()["id"]
    login = harness.client.post(
        "/v1/admin-sessions",
        json={"login_name": "mIxEd.aDmIn", "password": TEST_PASSWORD},
        headers={"Origin": ORIGIN},
    )
    assert login.status_code == 201 and login.json()["login_name"] == "mixed.admin"
    with harness.factory() as db:
        assert (
            db.scalar(
                select(AdminAccount.login_name).where(AdminAccount.id == created.json()["id"])
            )
            == "mixed.admin"
        )


@pytest.mark.parametrize("value", ["Kelvin", "ß", " admin", "admin "])
def test_normalization_does_not_expand_login_character_set(harness: Harness, value: str) -> None:
    response = harness.client.post(
        "/v1/admin-sessions",
        json={"login_name": value, "password": TEST_PASSWORD},
        headers={"Origin": ORIGIN},
    )
    assert response.status_code == 422
