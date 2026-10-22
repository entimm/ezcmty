import os
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select
from tests.support.imports.data import NOW, ImportSetup, create_batch

from backend_app.core.config import get_settings
from backend_app.integrations.import_files.errors import ImportFileError
from backend_app.integrations.import_files.storage import LocalImportStorage
from backend_app.models.imports import ImportArtifact, ImportBatch, ImportOperation, ImportRow
from backend_app.repositories.imports.tasks import ensure_task
from backend_app.services.worker.imports.retention import ImportRetentionService

EXPIRED = NOW + timedelta(days=31)


def _evidence(
    setup: ImportSetup,
    storage: LocalImportStorage,
    *,
    operation_status: str = "succeeded",
) -> tuple[str, str, str]:
    batch_id = create_batch(setup, status="blocked")
    stored = storage.write(f"{setup.company_id}/{batch_id}/source.csv", [b"code\nsecret\n"])
    with setup.factory() as db:
        operation = ImportOperation(
            property_company_id=setup.company_id,
            operation_key=batch_id.replace("-", "") * 2,
            operation_type="fixture_create",
            natural_key={"code": "secret"},
            input_fingerprint="b" * 64,
            status=operation_status,
            processed_at=NOW if operation_status in {"succeeded", "uncertain"} else None,
            created_at=NOW,
            updated_at=NOW,
        )
        db.add(operation)
        db.flush()
        db.add(
            ImportRow(
                batch_id=batch_id,
                source_row_no=2,
                raw_values={"code": "secret"},
                normalized_values={"code": "SECRET"},
                operation_id=operation.id,
                execution_status="created" if operation_status == "succeeded" else "pending",
                result_at=NOW if operation_status == "succeeded" else None,
            )
        )
        db.add(
            ImportArtifact(
                batch_id=batch_id,
                artifact_kind="source",
                generation=1,
                original_filename="sensitive_name.csv",
                storage_key=stored.key,
                media_type="text/csv",
                sha256=stored.sha256,
                byte_size=stored.byte_size,
                expires_at=NOW + timedelta(days=30),
                created_at=NOW,
                updated_at=NOW,
            )
        )
        db.commit()
        return batch_id, operation.id, stored.key


def _service(setup: ImportSetup, storage: LocalImportStorage) -> ImportRetentionService:
    return ImportRetentionService(setup.factory, get_settings(), storage)


def test_retention_destroys_sensitive_snapshots_after_thirty_days_and_preserves_history(
    import_setup: ImportSetup,
    tmp_path: Path,
) -> None:
    storage = LocalImportStorage(tmp_path / "objects")
    batch_id, operation_id, key = _evidence(import_setup, storage)
    service = _service(import_setup, storage)
    service.scan(now=NOW + timedelta(days=29))
    assert storage.path(key).exists()
    service.scan(now=EXPIRED)
    service.scan(now=EXPIRED)
    assert not storage.path(key).exists()
    with import_setup.factory() as db:
        artifact = db.scalars(
            select(ImportArtifact).where(ImportArtifact.batch_id == batch_id)
        ).one()
        row = db.scalars(select(ImportRow).where(ImportRow.batch_id == batch_id)).one()
        operation = db.get(ImportOperation, operation_id)
        assert artifact.deleted_at == EXPIRED and artifact.original_filename is None
        assert row.raw_values is None and row.normalized_values is None
        assert row.sensitive_cleared_at == EXPIRED and row.execution_status == "created"
        assert operation is not None and operation.natural_key is None
        assert operation.sensitive_cleared_at == EXPIRED and operation.status == "succeeded"
        assert operation.operation_key and operation.input_fingerprint == "b" * 64
        assert db.get(ImportBatch, batch_id) is not None


@pytest.mark.parametrize(
    "protection",
    ["ready", "running", "paused", "unknown_row", "unknown_operation", "unknown_counter"],
)
def test_expired_active_or_unknown_batch_keeps_all_recovery_evidence(
    import_setup: ImportSetup,
    tmp_path: Path,
    protection: str,
) -> None:
    storage = LocalImportStorage(tmp_path / "objects")
    batch_id, operation_id, key = _evidence(
        import_setup,
        storage,
        operation_status=(
            "uncertain"
            if protection == "unknown_operation"
            else "ready"
            if protection == "unknown_row"
            else "succeeded"
        ),
    )
    with import_setup.factory() as db:
        if protection in {"ready", "running", "paused"}:
            task = ensure_task(
                db,
                "precheck",
                batch_id,
                now=NOW,
                checkpoint={"schema_version": 1, "target_preview_version": 1, "next_row_no": 2},
            )
            task.status = protection
            task.lease_expires_at = EXPIRED if protection == "running" else None
        elif protection == "unknown_counter":
            batch = db.get(ImportBatch, batch_id)
            assert batch is not None
            batch.uncertain_rows = 1
        elif protection == "unknown_row":
            row = db.scalars(select(ImportRow).where(ImportRow.batch_id == batch_id)).one()
            row.execution_status = "uncertain"
            row.result_at = NOW
        db.commit()
    _service(import_setup, storage).scan(now=EXPIRED)
    assert storage.path(key).exists()
    with import_setup.factory() as db:
        row = db.scalars(select(ImportRow).where(ImportRow.batch_id == batch_id)).one()
        operation = db.get(ImportOperation, operation_id)
        assert row.raw_values == {"code": "secret"} and row.normalized_values == {"code": "SECRET"}
        assert row.sensitive_cleared_at is None
        assert operation is not None and operation.natural_key == {"code": "secret"}


def test_delete_failure_preserves_metadata_and_rows_then_succeeds_on_retry(
    import_setup: ImportSetup,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = LocalImportStorage(tmp_path / "objects")
    batch_id, _, key = _evidence(import_setup, storage)
    service = _service(import_setup, storage)
    original = storage.delete

    def unavailable(key: str) -> None:
        raise ImportFileError()

    monkeypatch.setattr(storage, "delete", unavailable)
    service.scan(now=EXPIRED)
    with import_setup.factory() as db:
        artifact = db.scalars(
            select(ImportArtifact).where(ImportArtifact.batch_id == batch_id)
        ).one()
        row = db.scalars(select(ImportRow).where(ImportRow.batch_id == batch_id)).one()
        assert artifact.deleted_at is None and artifact.original_filename == "sensitive_name.csv"
        assert row.raw_values == {"code": "secret"}
    assert storage.path(key).exists()
    monkeypatch.setattr(storage, "delete", original)
    service.scan(now=EXPIRED)
    assert not storage.path(key).exists()
    with import_setup.factory() as db:
        artifact = db.scalars(
            select(ImportArtifact).where(ImportArtifact.batch_id == batch_id)
        ).one()
        assert artifact.deleted_at == EXPIRED


def test_shared_operation_natural_key_survives_until_all_referencing_batches_expire(
    import_setup: ImportSetup,
    tmp_path: Path,
) -> None:
    storage = LocalImportStorage(tmp_path / "objects")
    _, operation_id, _ = _evidence(import_setup, storage)
    with import_setup.factory() as db:
        # The later batch's real retention remains open; clearing one batch cannot erase its key.
        batch = ImportBatch(
            property_company_id=import_setup.company_id,
            scope_type="company",
            scope_snapshot={"property_company_id": import_setup.company_id},
            template_key="fixture",
            template_version_no=1,
            template_config_hash="a" * 64,
            created_by_scope="platform_admin",
            created_by_id=import_setup.actor_id,
            request_id="later-batch",
            status="blocked",
            created_at=NOW + timedelta(days=10),
            retention_until=NOW + timedelta(days=40),
        )
        db.add(batch)
        db.flush()
        db.add(
            ImportRow(
                batch_id=batch.id,
                source_row_no=2,
                raw_values={"code": "secret"},
                operation_id=operation_id,
            )
        )
        db.commit()
    service = _service(import_setup, storage)
    service.scan(now=EXPIRED)
    with import_setup.factory() as db:
        operation = db.get(ImportOperation, operation_id)
        assert operation is not None and operation.natural_key == {"code": "secret"}
    service.scan(now=NOW + timedelta(days=41))
    with import_setup.factory() as db:
        operation = db.get(ImportOperation, operation_id)
        assert operation is not None and operation.natural_key is None


def test_protected_earlier_batches_do_not_starve_expired_unprotected_batch(
    import_setup: ImportSetup,
    tmp_path: Path,
) -> None:
    storage = LocalImportStorage(tmp_path / "objects")
    for _ in range(12):
        batch_id, _, _ = _evidence(import_setup, storage)
        with import_setup.factory() as db:
            ensure_task(
                db,
                "precheck",
                batch_id,
                now=NOW,
                checkpoint={"schema_version": 1, "target_preview_version": 1, "next_row_no": 2},
            )
            db.commit()
    _, _, key = _evidence(import_setup, storage)
    _service(import_setup, storage).scan(now=EXPIRED)
    assert not storage.path(key).exists()


def _age(storage: LocalImportStorage, key: str, when: datetime) -> None:
    stamp = when.timestamp()
    os.utime(storage.path(key), (stamp, stamp))


def test_orphan_scan_reclaims_old_unreferenced_objects_and_protects_active_generations(
    import_setup: ImportSetup,
    tmp_path: Path,
) -> None:
    storage = LocalImportStorage(tmp_path / "objects")
    batch_id = create_batch(import_setup, status="blocked")
    active = f"{import_setup.company_id}/{batch_id}/artifact/1/part-1.csv"
    unrelated = f"{import_setup.company_id}/00000000-0000-0000-0000-000000000000/source.csv"
    pending = ".pending-abandoned"
    fresh = "pending-fresh"
    for key in (active, unrelated, pending, fresh):
        storage.write(key, [b"test"])
        _age(storage, key, NOW)
    _age(storage, fresh, EXPIRED)
    with import_setup.factory() as db:
        ensure_task(
            db,
            "artifact",
            batch_id,
            now=NOW,
            checkpoint={
                "schema_version": 1,
                "source_preview_version": 1,
                "source_batch_row_version": 1,
                "output_generation": 1,
                "next_row_no": 2,
                "next_part_no": 1,
            },
        )
        db.commit()
    _service(import_setup, storage).scan(now=EXPIRED)
    assert storage.path(active).exists()
    assert not storage.path(unrelated).exists()
    assert not storage.path(pending).exists()
    assert storage.path(fresh).exists()


def test_draft_expires_at_twenty_four_hours_without_extending_retention(
    import_setup: ImportSetup,
    tmp_path: Path,
) -> None:
    batch_id = create_batch(import_setup)
    service = _service(import_setup, LocalImportStorage(tmp_path / "objects"))
    service.scan(now=NOW + timedelta(hours=23, minutes=59))
    with import_setup.factory() as db:
        batch = db.get(ImportBatch, batch_id)
        assert batch is not None and batch.status == "draft"
    service.scan(now=NOW + timedelta(hours=24))
    with import_setup.factory() as db:
        batch = db.get(ImportBatch, batch_id)
        assert batch is not None
        assert batch.status == "expired" and batch.finished_at == NOW + timedelta(hours=24)
        assert batch.retention_until == NOW + timedelta(days=30)
