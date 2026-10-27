from datetime import timedelta

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from tests.support.imports.adapter import test_definition as definition_factory
from tests.support.imports.data import NOW, ImportSetup, create_batch
from tests.support.paths import BACKEND_ROOT

from backend_app.core.identifiers import new_id
from backend_app.models.imports import ImportBatch, ImportRow


def _snapshot_row(
    setup: ImportSetup,
    *,
    status: str = "prechecking",
    confirmed: bool = False,
    retry: bool = False,
    pending: bool = True,
) -> tuple[str, str]:
    parent_id = create_batch(setup) if retry else None
    with setup.factory() as db:
        batch = ImportBatch(
            id=new_id(),
            parent_batch_id=parent_id,
            property_company_id=setup.company_id,
            scope_type="company",
            scope_snapshot={"name": "测试"},
            template_key="test_records",
            template_version_no=1,
            template_config_hash=definition_factory().config_hash,
            created_by_scope="platform_admin",
            created_by_id=setup.actor_id,
            request_id="snapshot-guard",
            status=status,
            retention_until=NOW + timedelta(days=30),
            confirmed_at=NOW if confirmed else None,
            apply_policy="all_rows" if confirmed else None,
            include_warning_rows=False if confirmed else None,
            finished_at=NOW if status == "completed" else None,
        )
        db.add(batch)
        db.flush()
        row = ImportRow(
            id=new_id(),
            batch_id=batch.id,
            source_row_no=2,
            raw_values={"name": "source"},
            normalized_values={"name": "source", "_prepared": {"generation": 1}},
            validation_version=1,
            execution_status="pending" if pending else "excluded",
            result_at=None if pending else NOW,
        )
        db.add(row)
        db.commit()
        return batch.id, row.id


def test_new_ordinary_precheck_generation_can_replace_preparation(
    import_setup: ImportSetup,
) -> None:
    _, row_id = _snapshot_row(import_setup)
    with import_setup.factory() as db:
        row = db.get(ImportRow, row_id)
        assert row is not None
        row.normalized_values = {"name": "source", "_prepared": {"generation": 2}}
        row.validation_version = 2
        db.commit()
    with import_setup.factory() as db:
        row = db.get(ImportRow, row_id)
        assert row is not None and row.normalized_values is not None
        assert row.raw_values == {"name": "source"}
        assert row.normalized_values["_prepared"] == {"generation": 2}


@pytest.mark.parametrize(
    "state",
    [
        "same_version",
        "confirmed",
        "retry",
        "completed",
        "not_pending",
        "not_prechecking",
        "raw",
    ],
)
def test_preparation_exception_does_not_weaken_other_history_guards(
    import_setup: ImportSetup,
    state: str,
) -> None:
    _, row_id = _snapshot_row(
        import_setup,
        confirmed=state == "confirmed",
        retry=state == "retry",
        status="completed"
        if state == "completed"
        else "draft"
        if state == "not_prechecking"
        else "prechecking",
        pending=state != "not_pending",
    )
    with import_setup.factory() as db, pytest.raises(IntegrityError) as caught:
        row = db.get(ImportRow, row_id)
        assert row is not None
        row.normalized_values = {"name": "source", "_prepared": {"generation": 2}}
        row.validation_version = 1 if state == "same_version" else 2
        if state == "raw":
            row.raw_values = {"name": "changed"}
        db.flush()
    assert (
        getattr(getattr(caught.value.orig, "diag", None), "constraint_name", None)
        == "ck_import_history_immutable"
    )


def test_preparation_migration_upgrade_and_safe_downgrade_preserve_evidence(
    import_setup: ImportSetup,
) -> None:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    batch_id, row_id = _snapshot_row(import_setup)
    command.downgrade(config, "20261022_imports")
    with import_setup.factory() as db, pytest.raises(IntegrityError):
        row = db.get(ImportRow, row_id)
        assert row is not None
        row.normalized_values = {"name": "source", "_prepared": {"generation": 2}}
        row.validation_version = 2
        db.flush()
    command.upgrade(config, "head")
    with import_setup.factory() as db:
        row = db.get(ImportRow, row_id)
        assert row is not None
        row.normalized_values = {"name": "source", "_prepared": {"generation": 2}}
        row.validation_version = 2
        db.commit()
    with pytest.raises(RuntimeError, match="recheck is active"):
        command.downgrade(config, "20261022_imports")
    with import_setup.factory() as db:
        assert (
            db.scalar(text("SELECT version_num FROM alembic_version"))
            == "20261027_client_identities"
        )
        batch = db.get(ImportBatch, batch_id)
        assert batch is not None
        batch.status, batch.preview_version = "preview_ready", 2
        batch.preview_fingerprint = "f" * 64
        batch.preview_expires_at = NOW + timedelta(days=1)
        db.commit()
    command.downgrade(config, "20261022_imports")
    with import_setup.factory() as db:
        row = db.get(ImportRow, row_id)
        assert row is not None and row.normalized_values is not None
        assert row.normalized_values["_prepared"] == {"generation": 2}
        assert row.raw_values == {"name": "source"}
