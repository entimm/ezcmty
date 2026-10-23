"""Bounded, generation-bound error file production; all filesystem I/O is outside transactions."""

import csv
import io
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from backend_app.core.config import Settings
from backend_app.domain.admin.identity import AdminIdentity
from backend_app.domain.imports.checkpoint import validate_checkpoint
from backend_app.domain.imports.registry import ImportRegistry
from backend_app.integrations.import_files.storage import LocalImportStorage, safe_csv_cell
from backend_app.models.admin import utc_now
from backend_app.models.imports import ImportArtifact, ImportBatch
from backend_app.repositories.admin import AdminRepository
from backend_app.repositories.imports import control, files
from backend_app.repositories.imports.batches import get_batch
from backend_app.repositories.imports.tasks import (
    TaskLease,
    advance_checkpoint,
    complete_task,
    require_current_lease,
    reschedule_task,
)
from backend_app.repositories.property import PropertyRepository

MAX_OUTPUT_BYTES = 100 * 1024 * 1024


def _guard(
    db: Session, lease: TaskLease, registry: ImportRegistry
) -> tuple[ImportBatch, dict[str, Any], str, tuple[str, ...]]:
    batch = get_batch(db, lease.batch_id, lock=True)
    if batch is None:
        raise ValueError("import.batch_state_conflict")
    task = require_current_lease(db, lease, now=utc_now())
    cp = validate_checkpoint("artifact", task.checkpoint)
    if (
        cp["source_preview_version"] != batch.preview_version
        or cp["source_batch_row_version"] != batch.row_version
    ):
        raise ValueError("import.preview_stale")
    if utc_now() >= batch.retention_until:
        raise ValueError("import.data_expired")
    definition = registry.get(
        batch.template_key, batch.template_version_no, batch.template_config_hash
    )
    event = files.generation_event(db, batch.id, cp["output_generation"])
    if event is None or not event.actor_id:
        raise ValueError("import.error_file_not_ready")
    identity = AdminIdentity(
        AdminRepository(
            db, "platform_admin" if batch.created_by_scope == "platform_admin" else "property_admin"
        )
    )
    account = identity.repo.identity(event.actor_id)
    if account is None or not account.enabled or account.must_change_password:
        raise ValueError("auth.forbidden")
    identity.bind_account(account)
    permissions = identity.effective_permissions(account.id)
    prefix = "platform" if batch.created_by_scope == "platform_admin" else "property"
    if f"{prefix}.import.generate_error_file" not in permissions or not set(
        definition.read_permissions
    ) <= set(permissions):
        raise ValueError("auth.forbidden")
    company = PropertyRepository(db).company(batch.property_company_id)
    community = (
        PropertyRepository(db).community(
            batch.community_id, company_scope_id=batch.property_company_id
        )
        if batch.community_id
        else None
    )
    if (
        not company
        or not company.enabled
        or batch.community_id
        and (not community or not community.enabled)
    ):
        raise ValueError("auth.forbidden")
    return (
        batch,
        cp,
        str(event.safe_metadata.get("format")),
        tuple(f.key for f in definition.fields if not f.sensitive),
    )


def generate_error_file(
    factory: sessionmaker[Session],
    settings: Settings,
    registry: ImportRegistry,
    storage: LocalImportStorage,
    lease: TaskLease,
) -> None:
    with factory() as db:
        batch, cp, file_format, field_keys = _guard(db, lease, registry)
        rows, issues, total = files.error_rows(db, batch, cp["next_row_no"], limit=100)
        company_id = batch.property_company_id
        batch_id = batch.id
        retention = batch.retention_until
        projected = []
        for row in rows:
            problems = [i for i in issues if i.row_id == row.id]
            # Never expose sensitive fields, even if the generating actor could read them.
            values = {k: v for k, v in (row.raw_values or {}).items() if k in field_keys}
            projected.append(
                [
                    row.source_row_no,
                    *[values.get(k) for k in field_keys],
                    row.execution_status,
                    ";".join(i.field_key or "" for i in problems),
                    ";".join(i.code for i in problems)
                    or (
                        "import.result_uncertain"
                        if row.execution_status == "uncertain"
                        else "import.system_error"
                    ),
                    ";".join(i.message for i in problems),
                    ";".join(i.suggestion or "" for i in problems),
                ]
            )
        next_row_no = rows[-1].source_row_no + 1 if rows else cp["next_row_no"]
        task_done = require_current_lease(db, lease, now=utc_now()).progress_done
        # Session closes and releases batch/task locks before writing any object.
    namespace = f"{company_id}/{batch_id}/artifact/{cp['output_generation']}"
    headers = [
        "row_no",
        *field_keys,
        "execution_status",
        "field_key",
        "code",
        "message",
        "suggestion",
    ]
    if projected:
        text = io.StringIO(newline="")
        writer = csv.writer(text)
        if cp["next_part_no"] == 1:
            writer.writerow(headers)
        writer.writerows([[safe_csv_cell(v) for v in row] for row in projected])
        storage.write(
            f"{namespace}/part-{cp['next_part_no']}.csv",
            io.BytesIO(text.getvalue().encode("utf-8")),
            max_bytes=MAX_OUTPUT_BYTES,
        )
        with factory() as db:
            current, latest, _, _ = _guard(db, lease, registry)
            if latest != cp:
                raise ValueError("import.checkpoint_invalid")
            new_cp = {**cp, "next_row_no": next_row_no, "next_part_no": cp["next_part_no"] + 1}
            advance_checkpoint(
                db,
                lease,
                now=utc_now(),
                checkpoint=new_cp,
                progress_done=task_done + len(rows),
                progress_total=total,
            )
            reschedule_task(db, lease, now=utc_now(), next_run_at=utc_now())
            db.commit()
        return
    # Merge already durable parts using bounded memory. The final object is still unpublished.
    import tempfile

    with tempfile.SpooledTemporaryFile(max_size=1024 * 1024, mode="w+b") as output:
        if file_format == "csv":
            output.write(b"\xef\xbb\xbf")
            for part in range(1, cp["next_part_no"]):
                with storage.open(f"{namespace}/part-{part}.csv") as source:
                    for chunk in iter(lambda: source.read(65536), b""):
                        output.write(chunk)
                        if output.tell() > MAX_OUTPUT_BYTES:
                            raise ValueError("import.file_too_large")
            media = "text/csv"
        elif file_format == "xlsx":
            from openpyxl import Workbook

            workbook = Workbook(write_only=True)
            sheet = workbook.create_sheet("导入问题")
            try:
                for part in range(1, cp["next_part_no"]):
                    with storage.open(f"{namespace}/part-{part}.csv") as source:
                        for output_row in csv.reader(
                            io.TextIOWrapper(source, encoding="utf-8", newline="")
                        ):
                            sheet.append(output_row)
                workbook.save(output)
            finally:
                workbook.close()
            media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        else:
            raise ValueError("import.file_invalid")
        output.seek(0)
        stored = storage.write(
            f"{namespace}/errors.{file_format}", output, max_bytes=MAX_OUTPUT_BYTES
        )
    with factory() as db:
        batch, latest, _, _ = _guard(db, lease, registry)
        if latest != cp:
            raise ValueError("import.checkpoint_invalid")
        now = utc_now()
        db.add(
            ImportArtifact(
                batch_id=batch.id,
                artifact_kind="error_rows",
                generation=cp["output_generation"],
                source_preview_version=cp["source_preview_version"],
                storage_key=stored.key,
                original_filename=None,
                media_type=media,
                sha256=stored.sha256,
                byte_size=stored.byte_size,
                row_count=total,
                expires_at=retention,
                created_at=now,
                updated_at=now,
            )
        )
        complete_task(db, lease, now=now)
        control.event(
            db,
            batch,
            f"error-file-published:{cp['output_generation']}",
            "artifact_published",
            now,
            task_id=lease.id,
            task_attempt=lease.attempt_count,
            metadata={"generation": cp["output_generation"], "phase": "artifact"},
        )
        db.commit()
