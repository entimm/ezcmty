from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from alembic import command
from alembic.config import Config
from pytest import MonkeyPatch
from sqlalchemy import MetaData, Table, create_engine, text
from sqlalchemy.orm import Session
from tests.support.audit import audit_filters
from tests.support.paths import BACKEND_ROOT

from backend_app.core.config import get_settings
from backend_app.core.identifiers import new_id
from backend_app.repositories.admin import AdminRepository


def test_audit_company_migration_preserves_all_existing_values(
    database_url: str, monkeypatch: MonkeyPatch
) -> None:
    url = database_url
    monkeypatch.setenv("APP_DATABASE_URL", url)
    get_settings.cache_clear()
    cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
    command.upgrade(cfg, "20261014_property_onboarding")
    engine = create_engine(url)
    old_table = Table("admin_audit_logs", MetaData(), autoload_with=engine)
    history_query = text(
        "SELECT id, scope, actor_id, actor_name, action, target_type, target_id, result, "
        "request_id, created_at, metadata FROM admin_audit_logs ORDER BY id"
    )
    legacy_company_id = new_id()
    metadata = {"property_company_id": legacy_company_id, "changed_fields": ["enabled"]}
    with engine.begin() as connection:
        for scope in ("platform_admin", "property_admin"):
            connection.execute(
                old_table.insert().values(
                    id=UUID(new_id()),
                    scope=scope,
                    actor_id=UUID(new_id()),
                    actor_name="历史操作人",
                    action="history.fixture",
                    target_type="account",
                    target_id=UUID(new_id()),
                    result="success",
                    request_id=scope,
                    created_at=datetime(2020, 1, 1, tzinfo=UTC),
                    metadata=metadata,
                )
            )
        old_values = connection.execute(history_query).all()
    command.upgrade(cfg, "head")
    with engine.connect() as connection:
        assert connection.execute(history_query).all() == old_values
        assert connection.execute(
            text("SELECT property_company_id FROM admin_audit_logs")
        ).all() == [(None,), (None,)]
    with Session(engine) as db:
        logs, total = AdminRepository(db, "property_admin", legacy_company_id).audit_logs(
            **audit_filters()
        )
        assert logs == [] and total == 0
        platform_logs, total = AdminRepository(db, "platform_admin").audit_logs(**audit_filters())
        assert total == 1 and platform_logs[0].safe_metadata == metadata
    engine.dispose()
