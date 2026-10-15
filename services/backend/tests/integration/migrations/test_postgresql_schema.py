from datetime import datetime, timedelta, timezone

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from pytest import MonkeyPatch
from sqlalchemy import inspect, select, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.exc import IntegrityError
from tests.support.admin import TEST_PASSWORD

from backend_app import cli
from backend_app.db.base import Base
from backend_app.db.session import get_engine, get_session_factory
from backend_app.models.admin import AdminAccount
from backend_app.models.property import Community, PropertyCompany
from backend_app.schemas.property import PropertyCompany as CompanyView


def test_fresh_schema_matches_models_and_native_timestamp_precision(
    migrated_database_url: str,
) -> None:
    with get_engine().connect() as connection:
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
        inspector = inspect(connection)
        timestamp_count = 0
        for table in Base.metadata.sorted_tables:
            for column in inspector.get_columns(table.name):
                if column["name"].endswith("_at"):
                    timestamp = column["type"]
                    assert isinstance(timestamp, TIMESTAMP)
                    assert timestamp.timezone and timestamp.precision == 6
                    timestamp_count += 1
                if table.name == "admin_audit_logs" and column["name"] == "metadata":
                    assert isinstance(column["type"], JSONB)
        assert timestamp_count == 9


def test_connection_settings_and_timestamp_roundtrip_preserve_utc_microseconds(
    migrated_database_url: str,
) -> None:
    with get_engine().connect() as connection:
        settings = connection.execute(
            text(
                "SELECT current_setting('TimeZone'), current_setting('transaction_isolation'), "
                "current_setting('statement_timeout'), current_setting('lock_timeout'), "
                "current_setting('idle_in_transaction_session_timeout')"
            )
        ).one()
        assert settings == ("UTC", "read committed", "10s", "3s", "1min")
    timestamp = datetime(2026, 1, 2, 12, 34, 56, 123456, tzinfo=timezone(timedelta(hours=8)))
    factory = get_session_factory()
    with factory() as db:
        company = PropertyCompany(
            code="TIME-01",
            name="时间",
            created_at=timestamp,
            updated_at=timestamp,
        )
        db.add(company)
        db.commit()
        identifier = company.id
    with factory() as db:
        db.execute(text("SET LOCAL TIME ZONE 'Asia/Shanghai'"))
        stored = db.get(PropertyCompany, identifier)
        assert stored and stored.created_at == timestamp
        assert stored.created_at.microsecond == 123456
        view = CompanyView.model_validate(stored).model_dump(mode="json")
        assert view["created_at"] == "2026-01-02T04:34:56.123456Z"
        assert view["updated_at"] == view["created_at"]


@pytest.mark.parametrize("kind", ["login", "company", "community"])
def test_database_rejects_noncanonical_identifiers(migrated_database_url: str, kind: str) -> None:
    with get_session_factory()() as db:
        company = PropertyCompany(code="COMPANY", name="公司")
        db.add(company)
        db.flush()
        row: AdminAccount | PropertyCompany | Community
        if kind == "login":
            row = AdminAccount(
                scope="platform_admin",
                login_name="Admin",
                display_name="管理员",
                password_hash="test-hash",
            )
            constraint = "ck_admin_account_login_lower"
        elif kind == "company":
            row = PropertyCompany(code="company", name="错误编码")
            constraint = "ck_property_company_code_upper"
        else:
            row = Community(
                property_company_id=company.id, code="community", name="小区", address="地址"
            )
            constraint = "ck_community_code_upper"
        with pytest.raises(IntegrityError) as caught, db.begin_nested():
            db.add(row)
            db.flush()
        assert getattr(caught.value.orig, "sqlstate", None) == "23514"
        assert (
            getattr(getattr(caught.value.orig, "diag", None), "constraint_name", None) == constraint
        )
        assert db.get(PropertyCompany, company.id) is not None


def test_cli_initialization_uses_normalized_name_and_rejects_duplicate_case(
    migrated_database_url: str,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sys.argv",
        [
            "backend_app.cli",
            "init-platform-admin",
            "--login-name",
            "Root.Admin",
            "--display-name",
            "平台",
        ],
    )
    monkeypatch.setattr(cli, "getpass", lambda prompt: TEST_PASSWORD)
    cli.main()
    with get_session_factory()() as db:
        assert db.scalar(select(AdminAccount.login_name)) == "root.admin"
    monkeypatch.setattr(
        "sys.argv",
        [
            "backend_app.cli",
            "init-platform-admin",
            "--login-name",
            "ROOT.ADMIN",
            "--display-name",
            "重复",
        ],
    )
    with pytest.raises(SystemExit) as caught:
        cli.main()
    assert caught.value.code == 2
