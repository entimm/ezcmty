from typing import Annotated, cast

import pytest
from fastapi import Depends, FastAPI
from sqlalchemy import func, insert, select
from sqlalchemy.orm import Session
from tests.support.admin import Harness
from tests.support.client_identities import SUBJECTS, identity_registry
from tests.support.resident import ResidentHarness

from backend_app.api.client.dependencies import get_client_identity_registry
from backend_app.core.identifiers import new_id
from backend_app.db.session import get_database_session
from backend_app.domain.client.types import ClientAuthorization
from backend_app.models.miniapp import MiniappUser, MiniappUserIdentity
from backend_app.services.client.identities import ClientIdentityRegistry, ClientIdentityService


def credentials(client: ResidentHarness) -> dict[str, str]:
    return {"Authorization": "Bearer " + client.token}


def test_empty_associations_derive_resident_without_database_writes(
    business_resident: ResidentHarness, business_harness: Harness
) -> None:
    client = business_resident
    client.login()
    for path in (
        "/v1/client-sessions/current",
        "/v1/miniapp-users/me",
        "/v1/miniapp-users/me/phone-bindings",
    ):
        response = client.client.get(path, headers=credentials(client))
        assert response.status_code == 200, response.text
    expected = {"id": "resident", "type": "resident", "display_name": "居民"}
    catalog = client.client.get("/v1/miniapp-users/me/identities", headers=credentials(client))
    assert catalog.json() == {"items": [expected], "total": 1, "page": 1, "page_size": 20}
    detail = client.client.get(
        "/v1/miniapp-users/me/identities/resident", headers=credentials(client)
    )
    assert detail.status_code == 200 and detail.json() == expected
    second = client.client.get(
        "/v1/miniapp-users/me/identities?page=2&page_size=1", headers=credentials(client)
    )
    assert second.json() == {"items": [], "total": 1, "page": 2, "page_size": 1}
    with business_harness.factory() as db:
        assert db.scalar(select(func.count()).select_from(MiniappUserIdentity)) == 0


@pytest.mark.parametrize("identity", [None, "invalid", "property"])
def test_resident_business_requires_well_formed_explicit_identity(
    business_resident: ResidentHarness, identity: str | None
) -> None:
    headers = credentials(business_resident)
    if identity is not None:
        headers["X-Client-Identity"] = identity
    response = business_resident.client.get("/v1/miniapp-users/me/house-bindings", headers=headers)
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert response.headers["cache-control"] == "no-store"


def test_unknown_identity_does_not_invalidate_client_or_public_account(
    business_resident: ResidentHarness,
) -> None:
    client = business_resident
    headers = {**credentials(client), "X-Client-Identity": new_id()}
    business = client.client.get("/v1/miniapp-users/me/house-bindings", headers=headers)
    assert business.status_code == 404
    public = client.client.get("/v1/miniapp-users/me/phone-bindings", headers=headers)
    assert public.status_code == 200
    resident = client.client.get("/v1/miniapp-users/me/house-bindings", headers=client.headers())
    assert resident.status_code == 200
    assert client.client.post("/v1/resident-sessions", json={"code": "legacy"}).status_code == 404


def test_unregistered_and_foreign_links_never_become_production_capabilities(
    business_resident: ResidentHarness, business_harness: Harness
) -> None:
    client = business_resident
    own_user = client.user_id
    client.login("foreign")
    other_user = client.user_id
    client.login()
    with business_harness.factory() as db:
        own = MiniappUserIdentity(
            user_id=own_user, identity_type="unregistered", subject_id=new_id()
        )
        other = MiniappUserIdentity(
            user_id=other_user, identity_type="unregistered", subject_id=new_id()
        )
        db.add_all([own, other])
        db.commit()
        own_id, other_id = own.id, other.id
    own_response = client.client.get(
        f"/v1/miniapp-users/me/identities/{own_id}", headers=credentials(client)
    )
    assert own_response.status_code == 403
    assert own_response.json()["code"] == "client.identity_unavailable"
    foreign_response = client.client.get(
        f"/v1/miniapp-users/me/identities/{other_id}", headers=credentials(client)
    )
    assert foreign_response.status_code == 404
    directory = client.client.get("/v1/miniapp-users/me/identities", headers=credentials(client))
    assert directory.status_code == 200 and directory.json()["total"] == 1
    assert directory.json()["items"][0]["id"] == "resident"
    for path in ("/v1/house-claims", "/v1/admin-sessions", "/v1/client-identities"):
        assert client.client.get(path, headers=credentials(client)).status_code == 404


def test_test_assembly_supports_multiple_identities_and_rejects_resident_type_mismatch(
    business_resident: ResidentHarness, business_harness: Harness
) -> None:
    client = business_resident
    with business_harness.factory() as db:
        SUBJECTS.create(db.connection())
        user = db.get(MiniappUser, client.user_id)
        assert user
        ctx = ClientAuthorization(user.id, user.session_version)
        first, second = new_id(), new_id()
        db.execute(
            insert(SUBJECTS),
            [
                {"id": first, "name": "测试业务甲", "enabled": True},
                {"id": second, "name": "测试业务乙", "enabled": True},
            ],
        )
        service = ClientIdentityService(db, identity_registry(db, "test_staff", "test_shop"))
        extra = service.grant(ctx, "test_staff", first)
        another = service.grant(ctx, "test_shop", second)
        db.commit()

    def registry(db: Annotated[Session, Depends(get_database_session)]) -> ClientIdentityRegistry:
        return identity_registry(db, "test_staff", "test_shop")

    app = cast(FastAPI, client.client.app)
    app.dependency_overrides[get_client_identity_registry] = registry
    directory = client.client.get(
        "/v1/miniapp-users/me/identities?page_size=2", headers=credentials(client)
    )
    assert directory.status_code == 200 and directory.json()["total"] == 3
    assert [item["id"] for item in directory.json()["items"]] == ["resident", extra.id]
    second_page = client.client.get(
        "/v1/miniapp-users/me/identities?page_size=2&page=2", headers=credentials(client)
    )
    assert second_page.json()["total"] == 3
    assert second_page.json()["items"] == [
        {"id": another.id, "type": "test_shop", "display_name": "测试业务乙"}
    ]
    detail = client.client.get(
        f"/v1/miniapp-users/me/identities/{extra.id}", headers=credentials(client)
    )
    assert detail.json() == {"id": extra.id, "type": "test_staff", "display_name": "测试业务甲"}
    mismatch = client.client.get(
        "/v1/miniapp-users/me/house-bindings",
        headers={**credentials(client), "X-Client-Identity": extra.id},
    )
    assert mismatch.status_code == 403
    assert mismatch.json()["code"] == "client.identity_mismatch"
    assert (
        client.client.get(
            "/v1/miniapp-users/me/house-bindings", headers=client.headers()
        ).status_code
        == 200
    )
    with business_harness.factory() as db:
        service = ClientIdentityService(db, identity_registry(db, "test_staff", "test_shop"))
        service.revoke(ctx, extra.id, expected_version=1)
        db.commit()
    revoked = client.client.get(
        f"/v1/miniapp-users/me/identities/{extra.id}", headers=credentials(client)
    )
    assert revoked.status_code == 403
    assert revoked.json()["code"] == "client.identity_unavailable"
    assert (
        client.client.get("/v1/miniapp-users/me/identities", headers=credentials(client)).json()[
            "total"
        ]
        == 2
    )
    assert (
        client.client.get("/v1/client-sessions/current", headers=credentials(client)).status_code
        == 200
    )


@pytest.mark.parametrize("invalidate", ["disabled", "version"])
def test_global_authentication_failure_is_distinct_from_identity_failure(
    business_resident: ResidentHarness, business_harness: Harness, invalidate: str
) -> None:
    client = business_resident
    with business_harness.factory() as db:
        user = db.get(MiniappUser, client.user_id)
        assert user
        if invalidate == "disabled":
            user.enabled = False
        else:
            user.session_version += 1
        db.commit()
    for path in (
        "/v1/client-sessions/current",
        "/v1/miniapp-users/me/identities",
        "/v1/miniapp-users/me/identities/resident",
        "/v1/miniapp-users/me/house-bindings",
    ):
        response = client.client.get(path, headers=client.headers())
        assert response.status_code == 401
        assert response.json()["code"] == "auth.unauthenticated"
        assert response.headers["www-authenticate"] == "Bearer"
        assert response.headers["cache-control"] == "no-store"
