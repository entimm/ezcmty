from io import BytesIO
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from backend_app.integrations.import_files.storage import LocalImportStorage
from backend_app.models.admin import utc_now
from backend_app.models.imports import ImportArtifact, ImportBatch
from backend_app.repositories.imports import control
from backend_app.repositories.imports.tasks import claim_tasks, ensure_task
from backend_app.services.worker.imports.pipeline import ImportWorkerService
from tests.support.imports.adapter import install_test_records
from tests.support.imports.data import ImportSetup, create_batch


def source_batch(
    setup: ImportSetup,
    storage: LocalImportStorage,
    source: bytes,
    *,
    extension: str = "csv",
    install_business_table: bool = True,
) -> str:
    batch_id = create_batch(setup)
    stored = storage.write(
        f"{setup.company_id}/{batch_id}/source/input.{extension}", BytesIO(source)
    )
    with setup.factory() as db:
        if install_business_table:
            install_test_records(db)
        batch = db.get(ImportBatch, batch_id)
        assert batch is not None
        now = utc_now()
        batch.status = "prechecking"
        artifact = ImportArtifact(
            batch_id=batch_id,
            artifact_kind="source",
            generation=1,
            storage_key=stored.key,
            sha256=stored.sha256,
            byte_size=stored.byte_size,
            media_type="text/csv"
            if extension == "csv"
            else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            expires_at=batch.retention_until,
            created_at=now,
            updated_at=now,
        )
        db.add(artifact)
        cursor: dict[str, Any] = (
            {"kind": "csv_record", "next_byte_offset": 0, "next_row_no": 1}
            if extension == "csv"
            else {"kind": "xlsx_row", "sheet_name": "导入数据", "next_row_no": 2}
        )
        ensure_task(
            db,
            "parse",
            batch_id,
            now=now,
            checkpoint={"schema_version": 1, "source_artifact_generation": 1, "cursor": cursor},
        )
        db.commit()
    return batch_id


def drain_worker(
    factory: sessionmaker[Session], worker: ImportWorkerService, *, max_dispatches: int = 1000
) -> int:
    for count in range(max_dispatches):
        with factory() as db:
            leases = claim_tasks(db, now=utc_now())
            db.commit()
        if not leases:
            return count
        worker.run(leases[0])
    raise AssertionError("Import worker exceeded bounded acceptance dispatches")


def confirm_preview(setup: ImportSetup, batch_id: str, *, warnings: bool = False) -> None:
    with setup.factory() as db:
        batch = db.scalars(
            select(ImportBatch).where(ImportBatch.id == batch_id).with_for_update()
        ).one()
        assert batch.status == "preview_ready", batch.last_error_code
        now = utc_now()
        control.exclude_rows(db, batch, warnings, now)
        batch.confirmed_at = now
        batch.apply_policy = "valid_rows_only"
        batch.include_warning_rows = warnings
        batch.status = "executing"
        batch.row_version += 1
        control.task(
            db,
            batch,
            "apply",
            {
                "schema_version": 1,
                "source_preview_version": batch.preview_version,
                "next_row_no": 1,
            },
            now,
        )
        db.commit()
