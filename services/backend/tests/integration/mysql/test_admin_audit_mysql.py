from __future__ import annotations

from datetime import datetime
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import MetaData, Table, delete, inspect, text
from sqlalchemy.dialects.mysql import BINARY
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker
from tests.support.paths import BACKEND_ROOT

from backend_app.core.admin_sessions import AdminSessionStore
from backend_app.core.identifiers import new_id
from backend_app.models.admin import AdminAuditLog
from backend_app.models.property import PropertyCompany
from backend_app.repositories.admin import AdminRepository


def test_mysql_audit_company_migration_preserves_history_and_indexes_company_queries(
    real_admin: tuple[sessionmaker[Session], AdminSessionStore],
) -> None:
    factory, _ = real_admin
    cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
    command.downgrade(cfg, "20261014_property_onboarding")
    history_query = text(
        "SELECT id, scope, actor_id, actor_name, action, target_type, target_id, result, "
        "request_id, created_at, metadata FROM admin_audit_logs "
        "WHERE action='history.fixture' ORDER BY id"
    )
    with factory() as db:
        old_table = Table("admin_audit_logs", MetaData(), autoload_with=db.connection())
        for scope in ("platform_admin", "property_admin"):
            db.execute(
                old_table.insert().values(
                    id=UUID(new_id()).bytes,
                    scope=scope,
                    actor_id=UUID(new_id()).bytes,
                    actor_name="历史操作人",
                    action="history.fixture",
                    target_type="account",
                    target_id=UUID(new_id()).bytes,
                    result="success",
                    request_id=scope,
                    created_at=datetime(2020, 1, 1),
                    metadata={"property_company_id": new_id(), "changed_fields": ["enabled"]},
                )
            )
        db.commit()
        old_values = db.execute(history_query).all()
    command.upgrade(cfg, "head")
    with factory() as db:
        assert db.execute(history_query).all() == old_values
        assert db.execute(text("SELECT property_company_id FROM admin_audit_logs")).all() == [
            (None,),
            (None,),
        ]
        inspector = inspect(db.connection())
        columns = {column["name"]: column for column in inspector.get_columns("admin_audit_logs")}
        company_column = columns["property_company_id"]
        assert company_column["nullable"] is True
        assert isinstance(company_column["type"], BINARY) and company_column["type"].length == 16
        indexes = {index["name"]: index for index in inspector.get_indexes("admin_audit_logs")}
        assert indexes["ix_admin_audit_company_time"]["column_names"] == [
            "scope",
            "property_company_id",
            "created_at",
            "id",
        ]
        foreign_keys = inspector.get_foreign_keys("admin_audit_logs")
        company_fk = next(item for item in foreign_keys if item["name"] == "fk_admin_audit_company")
        assert company_fk["constrained_columns"] == ["property_company_id"]
        assert company_fk["referred_table"] == "property_companies"
        assert company_fk["options"].get("ondelete") != "CASCADE"
        company = PropertyCompany(code="audit", name="审计公司")
        db.add(company)
        db.flush()
        log = AdminAuditLog(
            scope="property_admin",
            property_company_id=company.id,
            action="audit.fixture",
            target_type="account",
            result="success",
            request_id="new-company-audit",
        )
        db.add(log)
        db.flush()
        assert (
            db.execute(
                text("SELECT property_company_id FROM admin_audit_logs WHERE id=UUID_TO_BIN(:id)"),
                {"id": log.id},
            ).scalar_one()
            == UUID(company.id).bytes
        )
        logs, total = AdminRepository(db, "property_admin", company.id).audit_logs(
            page=1,
            page_size=20,
            from_time=None,
            to_time=None,
            action=None,
            result=None,
            request_id=None,
            sort="-created_at",
        )
        assert total == 1 and [row.id for row in logs] == [log.id]
        with pytest.raises(DBAPIError) as caught, db.begin_nested():
            db.execute(delete(PropertyCompany).where(PropertyCompany.id == company.id))
        assert caught.value.orig is not None and caught.value.orig.args[0] == 1451
        db.commit()
        log_id, company_id = log.id, company.id
    with pytest.raises(RuntimeError, match="existing audit records"):
        command.downgrade(cfg, "20261014_property_onboarding")
    with factory() as db:
        stored = db.get(AdminAuditLog, log_id)
        assert stored and stored.property_company_id == company_id
        assert db.execute(history_query).all() == old_values
