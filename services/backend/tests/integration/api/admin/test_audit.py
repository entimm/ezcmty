from __future__ import annotations

from collections.abc import Generator
from dataclasses import replace
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

import pytest
from fastapi import Depends, FastAPI, Query, Request
from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from sqlalchemy import select
from sqlalchemy.orm import Session
from tests.support.admin import ORIGIN, TEST_PASSWORD, Harness
from tests.support.audit import audit_filters, provision_company

from backend_app.api.admin import get_admin_session_store
from backend_app.app_factory import create_app
from backend_app.core.admin_sessions import AdminSessionStore
from backend_app.core.errors import AppError
from backend_app.core.identifiers import new_id
from backend_app.db.session import get_database_session
from backend_app.domain.admin.permissions import PermissionDefinition, permission_catalog
from backend_app.models.admin import AdminAccount, AdminAuditLog
from backend_app.models.property import PropertyCompany
from backend_app.schemas import admin as schema
from backend_app.schemas.mappers import admin as views
from backend_app.services.property_admin.admin import PropertyAdminService


def test_property_audit_http_isolates_companies_before_count_and_pagination(
    harness: Harness, monkeypatch: MonkeyPatch
) -> None:
    harness.login()
    first, _ = provision_company(harness, "first")
    second, _ = provision_company(harness, "second")
    timestamp = datetime.now(UTC).replace(tzinfo=None)
    own_ids = [new_id(), new_id()]
    with harness.factory() as db:
        for identifier, scope, company_id, result, metadata in (
            (own_ids[0], "property_admin", first, "success", {}),
            (own_ids[1], "property_admin", first, "failure", {}),
            (new_id(), "property_admin", second, "success", {"property_company_id": first}),
            (new_id(), "platform_admin", first, "success", {}),
            (new_id(), "property_admin", None, "success", {"property_company_id": first}),
        ):
            db.add(
                AdminAuditLog(
                    id=identifier,
                    scope=scope,
                    property_company_id=company_id,
                    action="audit.fixture",
                    target_type="account",
                    result=result,
                    request_id=identifier,
                    created_at=timestamp,
                    safe_metadata=metadata,
                )
            )
        db.commit()

    def catalog(scope: schema.AdminScope) -> list[PermissionDefinition]:
        if scope == "platform_admin":
            return permission_catalog(scope)
        return [
            PermissionDefinition(
                code="admin.audit.read", name="查看审计日志", group="审计", assignable=True
            )
        ]

    # Exercise the shared audit capability through a test-only HTTP adapter.
    # The property runtime itself does not expose an audit management route.
    monkeypatch.setattr("backend_app.domain.admin.identity.permission_catalog", catalog)
    app = create_app("property-admin-api")

    @app.get("/v1/admin-audit-logs", response_model=schema.AuditPage)
    def list_audit(
        request: Request,
        db: Annotated[Session, Depends(get_database_session)],
        store: Annotated[AdminSessionStore, Depends(get_admin_session_store)],
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 20,
        from_time: datetime | None = None,
        to_time: datetime | None = None,
        action: str | None = None,
        result: Literal["success", "failure"] | None = None,
        request_id: str | None = None,
        sort: Literal["created_at", "-created_at"] = "-created_at",
    ) -> schema.AuditPage:
        service = PropertyAdminService(db)
        context = service.authenticate(store, request.cookies.get("admin_session"))
        items, total = service.identity.audit.list_logs(
            context,
            **audit_filters(
                page=page,
                page_size=page_size,
                from_time=from_time.astimezone(UTC).replace(tzinfo=None) if from_time else None,
                to_time=to_time.astimezone(UTC).replace(tzinfo=None) if to_time else None,
                action=action,
                result=result,
                request_id=request_id,
                sort=sort,
            ),
        )
        return views.audit_page(items, total, page=page, page_size=page_size)

    def database() -> Generator[Session]:
        with harness.factory() as db:
            try:
                yield db
            except BaseException:
                db.rollback()
                raise

    app.dependency_overrides[get_database_session] = database
    app.dependency_overrides[get_admin_session_store] = lambda: harness.store
    outer = FastAPI()
    outer.mount("/api/property", app)
    with TestClient(outer, base_url="http://testserver/api/property") as client:
        assert client.get("/v1/admin-audit-logs").status_code == 401
        login = client.post(
            "/v1/admin-sessions",
            json={"login_name": "first", "password": TEST_PASSWORD},
            headers={"Origin": ORIGIN},
        )
        assert login.status_code == 201, login.text
        path = "/v1/admin-audit-logs"
        filters = {
            "action": "audit.fixture",
            "page_size": 1,
            "property_company_id": second,
            "scope": "platform_admin",
        }
        newest = client.get(path, params=filters)
        assert newest.status_code == 200, newest.text
        assert newest.json()["total"] == 2
        assert [row["id"] for row in newest.json()["items"]] == own_ids[1:]
        assert newest.json()["items"][0]["property_company_id"] == first
        assert newest.json()["items"][0]["metadata"] == {}
        older = client.get(path, params={**filters, "page": 2}).json()
        assert older["total"] == 2 and [row["id"] for row in older["items"]] == own_ids[:1]
        ascending = client.get(path, params={**filters, "sort": "created_at"}).json()
        assert [row["id"] for row in ascending["items"]] == own_ids[:1]
        successes = client.get(path, params={**filters, "result": "success"}).json()
        assert successes["total"] == 1
        assert [row["id"] for row in successes["items"]] == own_ids[:1]
        outside = client.get(path, params={**filters, "request_id": "missing"}).json()
        assert outside["total"] == 0 and outside["items"] == []
        outside_time = client.get(
            path, params={**filters, "to_time": "2000-01-01T00:00:00Z"}
        ).json()
        assert outside_time["total"] == 0 and outside_time["items"] == []
        monkeypatch.setattr(
            "backend_app.domain.admin.identity.permission_catalog", lambda scope: []
        )
        assert client.get(path).status_code == 403


def test_audit_http_returns_company_column_without_deriving_metadata(harness: Harness) -> None:
    harness.login()
    company_id, _ = provision_company(harness, "response")
    legacy_metadata = {"property_company_id": new_id(), "changed_fields": ["enabled"]}
    expected = {
        "current": (company_id, {}),
        "history": (None, legacy_metadata),
        "different-metadata": (company_id, legacy_metadata),
    }
    with harness.factory() as db:
        for request_id, (owner, metadata) in expected.items():
            db.add(
                AdminAuditLog(
                    id=new_id(),
                    scope="platform_admin",
                    property_company_id=owner,
                    action="audit.response-fixture",
                    target_type="company",
                    result="success",
                    request_id=request_id,
                    safe_metadata=metadata,
                )
            )
        db.commit()
    response = harness.client.get(
        "/v1/admin-audit-logs", params={"action": "audit.response-fixture"}
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["total"] == 3
    assert {
        row["request_id"]: (row["property_company_id"], row["metadata"]) for row in data["items"]
    } == expected


def test_property_audit_writes_trusted_ownership_for_operations_and_login_results(
    harness: Harness,
) -> None:
    harness.login()
    company_id, account_id = provision_company(harness, "writer")
    with harness.factory() as db:
        service = PropertyAdminService(db)
        token, _ = service.login(
            schema.AdminLogin(login_name="writer", password=TEST_PASSWORD),
            harness.store,
            "ip",
            "known-success",
        )
        context = service.authenticate(harness.store, token)
        service.update_profile(
            context, schema.ProfileUpdate(display_name="新名称"), "profile-update"
        )
        for login_name, request_id in (
            ("writer", "known-failure"),
            ("missing", "unknown-failure"),
        ):
            with pytest.raises(AppError) as caught:
                service.login(
                    schema.AdminLogin(login_name=login_name, password="wrong-password"),
                    harness.store,
                    "ip",
                    request_id,
                )
            assert caught.value.code == "auth.invalid_credentials"
        organization = db.get(PropertyCompany, company_id)
        assert organization
        organization.enabled = False
        db.commit()
        with pytest.raises(AppError) as caught:
            PropertyAdminService(db).login(
                schema.AdminLogin(login_name="writer", password=TEST_PASSWORD),
                harness.store,
                "ip",
                "disabled-company",
            )
        assert caught.value.code == "auth.invalid_credentials"
        logs = {
            row.request_id: row
            for row in db.scalars(
                select(AdminAuditLog).where(AdminAuditLog.scope == "property_admin")
            )
        }
        assert set(logs) == {
            "known-success",
            "profile-update",
            "known-failure",
            "unknown-failure",
            "disabled-company",
        }
        for request_id, row in logs.items():
            assert "property_company_id" not in row.safe_metadata
            if request_id == "unknown-failure":
                assert row.property_company_id is None and row.actor_id is None
            else:
                assert row.property_company_id == company_id and row.actor_id == account_id
        assert logs["profile-update"].safe_metadata == {"changed_fields": ["display_name"]}


def test_audit_domain_rejects_missing_or_mismatched_authorization_context(
    harness: Harness,
) -> None:
    harness.login()
    company_id, account_id = provision_company(harness, "reader")
    with harness.factory() as db:
        service = PropertyAdminService(db)
        token, _ = service.login(
            schema.AdminLogin(login_name="reader", password=TEST_PASSWORD),
            harness.store,
            "ip",
            "read-login",
        )
        authenticated = service.authenticate(harness.store, token)
        allowed = replace(authenticated, permissions=["admin.audit.read"])
        for context in (
            authenticated,
            replace(allowed, property_company_id=None),
            replace(allowed, property_company_id=new_id()),
            replace(allowed, scope="platform_admin"),
        ):
            with pytest.raises(AppError) as caught:
                service.identity.audit.list_logs(context, **audit_filters())
            assert caught.value.code == "auth.forbidden"
        with pytest.raises(AppError) as caught:
            service.identity.audit.list_logs(
                replace(allowed, must_change_password=True), **audit_filters()
            )
        assert caught.value.code == "auth.password_change_required"
        unbound = PropertyAdminService(db)
        with pytest.raises(AppError) as caught:
            unbound.identity.audit.list_logs(
                replace(allowed, property_company_id=None), **audit_filters()
            )
        assert caught.value.code == "auth.forbidden"
        with pytest.raises(ValueError, match="company context"):
            unbound.identity.repo.audit_logs(**audit_filters())
        account = db.get(AdminAccount, account_id)
        assert account
        write: dict[str, Any] = {
            "actor": account,
            "action": "account.update",
            "target_type": "account",
            "target_id": account_id,
            "request_id": "trusted-write",
        }
        with pytest.raises(AppError) as caught:
            unbound.identity.audit.record(**write)
        assert caught.value.code == "auth.forbidden"
        with pytest.raises(AppError) as caught:
            service.identity.audit.record(**write, property_company_id=new_id())
        assert caught.value.code == "auth.forbidden"
        service.identity.audit.record(**write, metadata={"property_company_id": new_id()})
        db.commit()
        items, total = service.identity.audit.list_logs(allowed, **audit_filters())
        assert total == 2 and all(
            row.property_company_id == company_id and row.safe_metadata == {} for row in items
        )
        stored = db.scalar(select(AdminAuditLog).where(AdminAuditLog.request_id == "trusted-write"))
        assert stored and stored.safe_metadata == {}
