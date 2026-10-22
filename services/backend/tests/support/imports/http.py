"""Persistent HTTP arrangements; the processing chain is exercised by Worker tests."""

from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any

from pytest import MonkeyPatch
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from backend_app.core.config import get_settings
from backend_app.domain.imports.fingerprints import fingerprint
from backend_app.domain.imports.registry import ImportDefinition
from backend_app.import_definitions.catalog import JsonImportRegistry
from backend_app.integrations.import_files.storage import LocalImportStorage
from backend_app.models.admin import utc_now
from backend_app.models.imports import (
    ImportArtifact,
    ImportBatch,
    ImportIssue,
    ImportOperation,
    ImportRow,
    ImportTask,
)
from tests.support.imports.adapter import TestRecordAdapter
from tests.support.imports.adapter import test_definition as definition_factory


def install_http_registry(
    monkeypatch: MonkeyPatch,
    directory: Path,
    *,
    sensitive: bool = False,
    required_permissions: tuple[str, ...] = (),
    adapter: TestRecordAdapter | None = None,
) -> tuple[ImportDefinition, LocalImportStorage]:
    definition = definition_factory()
    definition = replace(
        definition,
        fields=tuple(
            replace(field, sensitive=field.key == "name" and sensitive)
            for field in definition.fields
        ),
        required_permissions=required_permissions,
        released_at="2026-10-23T00:00:00Z",
    )
    registry = JsonImportRegistry((definition,), {"test_records": adapter or TestRecordAdapter()})
    monkeypatch.setattr("backend_app.services.imports.access.get_import_registry", lambda: registry)
    root = directory.resolve() / "private-imports"
    monkeypatch.setenv("APP_IMPORT_STORAGE_ROOT", str(root))
    get_settings.cache_clear()
    return definition, LocalImportStorage(root)


def publish_http_preview(
    factory: sessionmaker[Session],
    batch_id: str,
    *,
    invalid: bool = False,
) -> None:
    """Arrange an already published generation to test the HTTP transaction boundary."""
    now = utc_now()
    with factory() as db:
        batch = db.get(ImportBatch, batch_id)
        assert batch
        tasks = db.scalars(select(ImportTask).where(ImportTask.batch_id == batch_id)).all()
        for task in tasks:
            task.status = "completed"
            task.lease_expires_at = None
            task.completed_at = now
        batch.status = "preview_ready"
        batch.preview_version = 1
        batch.preview_fingerprint = "b" * 64
        batch.preview_expires_at = min(now + timedelta(hours=24), batch.retention_until)
        batch.total_rows = 2
        batch.planned_create_rows = 1 if invalid else 2
        batch.error_rows = int(invalid)
        batch.row_version += 1
        batch.updated_at = now
        db.add(
            ImportTask(
                batch_id=batch_id,
                phase="precheck",
                status="completed",
                checkpoint={"schema_version": 1, "target_preview_version": 1, "next_row_no": 4},
                next_run_at=now,
                progress_done=2,
                progress_total=2,
                completed_at=now,
            )
        )
        for number in (2, 3):
            bad = invalid and number == 3
            row = ImportRow(
                batch_id=batch_id,
                source_row_no=number,
                raw_values={"code": f"c{number}", "name": "private-value"},
                normalized_values={"code": f"C{number}", "name": "private-value"},
                validation_status="invalid" if bad else "valid",
                validation_version=1,
                planned_action="none" if bad else "create",
                error_count=int(bad),
            )
            if not bad:
                operation = ImportOperation(
                    property_company_id=batch.property_company_id,
                    operation_key=fingerprint({"batch": batch_id, "row": number}),
                    operation_type="test_record.create",
                    natural_key={"code": f"C{number}"},
                    input_fingerprint=fingerprint(row.normalized_values),
                )
                db.add(operation)
                db.flush()
                row.operation_id = operation.id
            db.add(row)
            db.flush()
            if bad:
                db.add(
                    ImportIssue(
                        batch_id=batch_id,
                        row_id=row.id,
                        preview_version=1,
                        phase="precheck",
                        severity="error",
                        code="import.invalid_format",
                        field_key="name",
                        column_name="名称",
                        column_index=2,
                        cell_reference="B3",
                        message="名称不符合要求",
                        suggestion="修改名称",
                    )
                )
        db.commit()


def publish_http_error_file(
    factory: sessionmaker[Session],
    batch_id: str,
    storage: LocalImportStorage,
) -> None:
    """Arrange a completed private artifact to test authorization and streaming delivery."""
    content = b"code,name\nC3,***\n"
    stored = storage.write(f"errors/{batch_id}/1.csv", (content,))
    with factory() as db:
        batch = db.get(ImportBatch, batch_id)
        assert batch
        task = db.scalar(
            select(ImportTask).where(
                ImportTask.batch_id == batch_id, ImportTask.phase == "artifact"
            )
        )
        assert task
        task.status = "completed"
        task.completed_at = utc_now()
        db.add(
            ImportArtifact(
                batch_id=batch_id,
                artifact_kind="error_rows",
                generation=1,
                source_preview_version=batch.preview_version,
                storage_key=stored.key,
                media_type="text/csv",
                sha256=stored.sha256,
                byte_size=stored.byte_size,
                expires_at=batch.retention_until,
            )
        )
        db.commit()


def create_body(company_id: str, *, platform: bool = False) -> dict[str, Any]:
    return {
        "import_type": "test_records",
        "template_version_no": 1,
        "scope": {"type": "company", "id": company_id},
        "mode": "create",
        **({"property_company_id": company_id} if platform else {}),
    }
