from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session, sessionmaker

from backend_app.core.identifiers import new_id
from backend_app.models.admin import AdminAccount, AdminAccountRole, AdminRole
from backend_app.models.imports import ImportBatch
from backend_app.models.property import PropertyCompany
from tests.support.imports.adapter import test_definition

NOW = datetime(2026, 10, 23, tzinfo=UTC)


@dataclass(frozen=True)
class ImportSetup:
    factory: sessionmaker[Session]
    company_id: str
    actor_id: str


def provision_imports(factory: sessionmaker[Session]) -> ImportSetup:
    with factory() as db:
        company = PropertyCompany(code="IMPORT_TEST", name="Import Test", enabled=True)
        actor = AdminAccount(
            scope="platform_admin",
            login_name="import_actor",
            display_name="Import Actor",
            password_hash="test-only",
            enabled=True,
            must_change_password=False,
        )
        db.add_all([company, actor])
        db.flush()
        role = AdminRole(
            scope="platform_admin",
            code="super_admin",
            name="Import Root",
            is_system=True,
            enabled=True,
        )
        db.add(role)
        db.flush()
        db.add(AdminAccountRole(scope="platform_admin", account_id=actor.id, role_id=role.id))
        result = ImportSetup(factory, company.id, actor.id)
        db.commit()
        return result


def create_batch(setup: ImportSetup, *, status: str = "draft") -> str:
    with setup.factory() as db:
        batch = ImportBatch(
            id=new_id(),
            property_company_id=setup.company_id,
            scope_type="company",
            scope_snapshot={"property_company_id": setup.company_id},
            template_key="test_records",
            template_version_no=1,
            template_config_hash=test_definition().config_hash,
            created_by_scope="platform_admin",
            created_by_id=setup.actor_id,
            request_id="import-test",
            status=status,
            retention_until=NOW + timedelta(days=30),
            created_at=NOW,
            updated_at=NOW,
        )
        db.add(batch)
        db.commit()
        return batch.id
