"""Bounded import stages with durable coordinates and transaction-owned business writes."""

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime, timedelta
from types import MappingProxyType
from typing import Any, cast

from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from backend_app.core.config import Settings
from backend_app.core.errors import AppError
from backend_app.domain.admin.identity import AdminIdentity
from backend_app.domain.admin.types import AdminScope
from backend_app.domain.imports.checkpoint import validate_checkpoint
from backend_app.domain.imports.errors import ImportExecutionFailure, ImportOutcomeUnknown
from backend_app.domain.imports.fingerprints import canonical_json, fingerprint
from backend_app.domain.imports.lifecycle import validate_transition
from backend_app.domain.imports.operation_keys import operation_key
from backend_app.domain.imports.registry import ImportDefinition, ImportRegistry
from backend_app.domain.imports.types import ImportContext, ImportProblem, ImportScope
from backend_app.domain.imports.validation import normalize_fields, validate_fields
from backend_app.import_definitions.catalog import get_import_registry
from backend_app.integrations.import_files.csv_parser import parse_csv_chunk
from backend_app.integrations.import_files.errors import ImportFileError
from backend_app.integrations.import_files.storage import LocalImportStorage
from backend_app.integrations.import_files.xlsx_parser import parse_xlsx_chunk
from backend_app.models.admin import utc_now
from backend_app.models.imports import ImportBatch, ImportOperation, ImportRow, ImportTask
from backend_app.repositories.admin import AdminRepository
from backend_app.repositories.imports import control
from backend_app.repositories.imports import pipeline as records
from backend_app.repositories.imports.artifacts import source_artifact
from backend_app.repositories.imports.batches import get_batch
from backend_app.repositories.imports.issues import add_issue
from backend_app.repositories.imports.operations import ensure_operation, get_operation
from backend_app.repositories.imports.rows import read_rows, stage_rows
from backend_app.repositories.imports.tasks import (
    LeaseLost,
    TaskLease,
    advance_checkpoint,
    complete_task,
    pause_task,
    require_current_lease,
    reschedule_task,
)
from backend_app.repositories.property import PropertyRepository
from backend_app.services.imports.permissions import (
    batch_permissions,
    prepared_values,
    require_permissions,
    source_values,
)
from backend_app.services.worker.imports.adapters.base import ImportAdapter

CHUNK_ROWS = 200


class ImportWorkerService:
    def __init__(
        self,
        factory: sessionmaker[Session],
        settings: Settings,
        registry: ImportRegistry | None = None,
        storage: LocalImportStorage | None = None,
    ) -> None:
        self.factory = factory
        self.settings = settings
        self.registry = registry if registry is not None else get_import_registry()
        self.storage = storage or LocalImportStorage(settings.import_storage_root)

    def run(self, lease: TaskLease) -> None:
        try:
            with self.factory() as db:
                batch = get_batch(db, lease.batch_id, lock=True)
                if batch is not None and batch.status == "cancel_requested":
                    require_current_lease(db, lease, now=utc_now())
                    self._cancel(db, batch, lease, utc_now())
                    db.commit()
                    return
            if lease.phase == "parse":
                self._parse(lease)
            elif lease.phase == "precheck":
                self._precheck(lease)
            elif lease.phase == "apply":
                self._apply(lease)
            elif lease.phase == "artifact":
                from backend_app.services.worker.imports.error_file import generate_error_file

                generate_error_file(self.factory, self.settings, self.registry, self.storage, lease)
            else:
                self._pause(lease, "import.checkpoint_invalid")
        except LeaseLost:
            raise
        except ImportFileError as error:
            if lease.phase == "parse":
                self._parse_error(lease, error.code)
            else:
                self._pause(lease, error.code)
        except AppError as error:
            self._pause(lease, error.code)
        except ValueError as error:
            code = str(error)
            self._pause(
                lease,
                code
                if re.fullmatch(r"(?:import|auth)\.[a-z_]{1,96}", code)
                else "import.checkpoint_invalid",
            )
        except OSError, DBAPIError:
            self._pause(lease, "import.system_error")
        except Exception:
            # Diagnostics do not include adapter input, SQL, or exception messages.
            self._pause(lease, "import.system_error")

    def _guard(
        self,
        db: Session,
        lease: TaskLease,
    ) -> tuple[ImportBatch, ImportTask, ImportDefinition, ImportContext]:
        batch = get_batch(db, lease.batch_id, lock=True)
        if batch is None:
            raise LeaseLost
        task = require_current_lease(db, lease, now=utc_now())
        validate_checkpoint(lease.phase, task.checkpoint)
        definition = self.registry.get(
            batch.template_key, batch.template_version_no, batch.template_config_hash
        )
        if batch.created_by_scope not in definition.allowed_actor_scopes:
            raise ValueError("auth.forbidden")
        identity = AdminIdentity(AdminRepository(db, cast(AdminScope, batch.created_by_scope)))
        actor = identity.repo.identity(batch.created_by_id)
        if actor is None or not actor.enabled or actor.must_change_password:
            raise ValueError("auth.forbidden")
        identity.bind_account(actor)
        if (
            actor.scope == "property_admin"
            and actor.property_company_id != batch.property_company_id
        ):
            raise ValueError("auth.forbidden")
        permissions = frozenset(identity.effective_permissions(actor.id))
        prefix = "platform" if actor.scope == "platform_admin" else "property"
        action = {
            "parse": "upload",
            "precheck": "precheck",
            "apply": "execute",
            "artifact": "generate_error_file",
        }[lease.phase]
        if (
            f"{prefix}.import.{action}" not in permissions
            or not set(definition.required_permissions) <= permissions
        ):
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
            company is None
            or not company.enabled
            or batch.community_id
            and (community is None or not community.enabled)
            or batch.scope_type not in definition.allowed_scope_types
        ):
            raise ValueError("import.scope_mismatch")
        context = ImportContext(
            actor.scope,
            actor.id,
            ImportScope(
                batch.property_company_id,
                batch.scope_type,
                batch.community_id,
                batch.scope_snapshot,
            ),
            batch.request_id,
            permissions,
            phase=lease.phase,
        )
        return batch, task, definition, context

    @staticmethod
    def _cancel(db: Session, batch: ImportBatch, lease: TaskLease, now: datetime) -> bool:
        if batch.status != "cancel_requested":
            return False
        control.recalculate(db, batch)
        if batch.uncertain_rows:
            batch.status = "blocked"
            batch.finished_at = None
            batch.last_error_code = "import.result_uncertain"
            pause_task(db, lease, now=now, error_code="import.result_uncertain")
        else:
            complete_task(db, lease, now=utc_now())
            control.cancel_remaining(db, batch, now)
            batch.row_version += 1
        control.event(
            db,
            batch,
            f"cancelled:{lease.id}:{lease.attempt_count}",
            "cancelled",
            now,
            task_id=lease.id,
            task_attempt=lease.attempt_count,
        )
        return True

    def _parse(self, lease: TaskLease) -> None:
        # Read only stable identities; all file reads happen after this transaction ends.
        with self.factory() as db:
            batch, task, definition, _ = self._guard(db, lease)
            if self._cancel(db, batch, lease, utc_now()):
                db.commit()
                return
            artifact = source_artifact(db, batch.id)
            if artifact is None or artifact.deleted_at is not None:
                raise ValueError("import.file_invalid")
            cp = dict(task.checkpoint)
            if cp["source_artifact_generation"] != artifact.generation:
                raise ValueError("import.source_generation_mismatch")
            key, sha, size, media = (
                artifact.storage_key,
                artifact.sha256,
                artifact.byte_size,
                artifact.media_type,
            )
            db.rollback()
        self.storage.verify(key, expected_sha256=sha, expected_size=size)
        cursor = cp["cursor"]
        if media == "text/csv":
            if cursor["kind"] != "csv_record":
                raise ValueError("import.checkpoint_invalid")
            chunk = parse_csv_chunk(
                self.storage.path(key),
                next_byte_offset=cursor["next_byte_offset"],
                next_row_no=cursor["next_row_no"],
                limit=CHUNK_ROWS,
                expected_headers=definition.headers,
            )
            next_cursor = {
                "kind": "csv_record",
                "next_byte_offset": chunk.next_byte_offset,
                "next_row_no": chunk.next_row_no,
            }
        else:
            if cursor["kind"] != "xlsx_row" or cursor["sheet_name"] != definition.sheet_name:
                raise ValueError("import.checkpoint_invalid")
            chunk = parse_xlsx_chunk(
                self.storage.path(key),
                sheet_name=cursor["sheet_name"],
                next_row_no=cursor["next_row_no"],
                limit=CHUNK_ROWS,
                expected_headers=definition.headers,
            )
            next_cursor = {
                "kind": "xlsx_row",
                "sheet_name": definition.sheet_name,
                "next_row_no": chunk.next_row_no,
            }
        with self.factory() as db:
            batch, task, _, _ = self._guard(db, lease)
            now = utc_now()
            if self._cancel(db, batch, lease, now):
                db.commit()
                return
            stage_rows(
                db,
                batch.id,
                [
                    (
                        row.source_row_no,
                        dict(
                            zip((field.key for field in definition.fields), row.values, strict=True)
                        ),
                    )
                    for row in chunk.rows
                ],
                now=now,
            )
            control.recalculate(db, batch)
            cp["cursor"] = next_cursor
            advance_checkpoint(
                db,
                lease,
                now=now,
                checkpoint=cp,
                progress_done=batch.total_rows if chunk.done else 0,
                progress_total=batch.total_rows if chunk.done else 0,
            )
            batch.updated_at = now
            if chunk.done:
                complete_task(db, lease, now=utc_now())
                if batch.total_rows == 0:
                    add_issue(
                        db,
                        batch_id=batch.id,
                        preview_version=0,
                        phase="parse",
                        severity="error",
                        code="import.file_empty",
                        message="源文件没有数据行",
                        created_at=now,
                    )
                    batch.status, batch.finished_at = "failed", now
                    batch.last_error_code = "import.file_empty"
                else:
                    control.task(
                        db,
                        batch,
                        "precheck",
                        {
                            "schema_version": 1,
                            "target_preview_version": batch.preview_version + 1,
                            "next_row_no": 1,
                        },
                        now,
                    )
                control.event(
                    db,
                    batch,
                    "parse_completed",
                    "parsed",
                    now,
                    task_id=lease.id,
                    task_attempt=lease.attempt_count,
                )
            else:
                reschedule_task(db, lease, now=utc_now(), next_run_at=now)
            batch.row_version += 1
            db.commit()

    def _issue(
        self,
        db: Session,
        batch: ImportBatch,
        row: ImportRow,
        version: int,
        problem: ImportProblem,
        now: datetime,
        *,
        phase: str = "precheck",
    ) -> None:
        definition = self.registry.get(
            batch.template_key, batch.template_version_no, batch.template_config_hash
        )
        fields = {field.key: field for field in definition.fields}
        field = fields.get(problem.field_key or "")
        column_index = field.order if field else problem.column_index
        if type(column_index) is not int or not 1 <= column_index <= 200:
            column_index = None
        column_name = field.label if field else (f"第{column_index}列" if column_index else None)
        if not re.fullmatch(r"import\.[a-z_]{1,96}", problem.code) or problem.severity not in {
            "warning",
            "error",
        }:
            raise ValueError("import.adapter_result_invalid")
        detail = None
        if field is not None and problem.detail:
            detail = {"expected_type": field.data_type}
        cell = problem.cell_reference
        if cell is not None and not re.fullmatch(r"[A-Z]{1,3}[1-9][0-9]{0,6}", cell):
            cell = None
        add_issue(
            db,
            batch_id=batch.id,
            row_id=row.id,
            preview_version=version,
            phase=phase,
            severity=problem.severity,
            code=problem.code,
            field_key=field.key if field else None,
            column_name=column_name,
            column_index=column_index,
            cell_reference=cell,
            message=problem.message[:1000],
            suggestion=problem.suggestion[:1000] if problem.suggestion else None,
            detail=detail,
            created_at=now,
        )

    def _precheck(self, lease: TaskLease) -> None:
        with self.factory() as db:
            batch, task, definition, context = self._guard(db, lease)
            now = utc_now()
            if self._cancel(db, batch, lease, now):
                db.commit()
                return
            if batch.confirmed_at is not None:
                raise ValueError("import.batch_state_conflict")
            cp = dict(task.checkpoint)
            version = cp["target_preview_version"]
            if version != batch.preview_version + 1:
                raise ValueError("import.checkpoint_invalid")
            adapter = cast(ImportAdapter, self.registry.get_adapter(definition.adapter_key))
            rows = read_rows(
                db, batch.id, next_row_no=cp["next_row_no"], limit=CHUNK_ROWS, lock=True
            )
            for row in rows:
                if row.raw_values is None:
                    raise ValueError("import.data_expired")
                fixed = prepared_values(row.normalized_values) if batch.parent_batch_id else None
                if batch.parent_batch_id and (fixed is None or row.operation_id is None):
                    raise ValueError("import.operation_identity_mismatch")
                normalized = (
                    source_values(row.normalized_values or {})
                    if fixed is not None
                    else adapter.normalize(normalize_fields(definition, row.raw_values))
                )
                require_permissions(
                    adapter.required_permissions(normalized, fixed), context.permissions
                )
                problems = validate_fields(definition, normalized)
                preparation = adapter.prepare(
                    MappingProxyType(normalized),
                    context,
                    db,
                    fixed_prepared=json.loads(canonical_json(fixed)) if fixed is not None else None,
                )
                problems.extend(preparation.problems)
                if fixed is not None and preparation.prepared not in (None, fixed):
                    raise ValueError("import.operation_identity_mismatch")
                prepared = fixed if fixed is not None else preparation.prepared
                identity = (
                    (row.normalized_values or {}).get("_identity")
                    if fixed is not None
                    else preparation.identity
                )
                if identity is not None and (
                    not isinstance(identity, dict)
                    or set(identity) != {"operation_type", "natural_key"}
                    or not isinstance(identity["operation_type"], str)
                    or not identity["operation_type"]
                    or not isinstance(identity["natural_key"], dict)
                    or not identity["natural_key"]
                ):
                    raise ValueError("import.adapter_result_invalid")
                require_permissions(
                    adapter.required_permissions(normalized, prepared), context.permissions
                )
                plan = (
                    adapter.plan(prepared)
                    if prepared is not None and not any(p.severity == "error" for p in problems)
                    else None
                )
                if prepared is None and not any(p.severity == "error" for p in problems):
                    problems.append(ImportProblem("import.conflict", "未获得可执行的业务准备结果"))
                if plan is not None and (
                    plan.action not in {"create", "skip"}
                    or not plan.operation_type
                    or not plan.natural_key
                ):
                    problems.append(ImportProblem("import.conflict", "无法建立创建操作计划"))
                    plan = None
                if plan is not None:
                    planned_identity = {
                        "operation_type": plan.operation_type,
                        "natural_key": plan.natural_key,
                    }
                    if identity is not None and identity != planned_identity:
                        raise ValueError("import.operation_identity_mismatch")
                    if fixed is None:
                        identity = planned_identity
                    input_hash = plan.input_fingerprint or fingerprint(prepared)
                    stable_key = operation_key(
                        batch.property_company_id,
                        batch.template_key,
                        plan.operation_type or "",
                        plan.natural_key or {},
                        input_hash,
                    )
                    if batch.parent_batch_id:
                        assert row.operation_id is not None
                        operation = get_operation(db, row.operation_id, lock=True)
                        if (
                            operation is None
                            or operation.property_company_id != batch.property_company_id
                            or (
                                operation.operation_type != plan.operation_type
                                or operation.input_fingerprint != input_hash
                                or operation.operation_key != stable_key
                            )
                        ):
                            raise ValueError("import.operation_identity_mismatch")
                    else:
                        operation = ensure_operation(
                            db,
                            property_company_id=batch.property_company_id,
                            operation_key=stable_key,
                            operation_type=plan.operation_type or "",
                            natural_key=plan.natural_key or {},
                            input_fingerprint=input_hash,
                            now=now,
                        )
                        row.operation_id = operation.id
                    if operation.status in {"succeeded", "skipped"}:
                        assert prepared is not None
                        problems.extend(
                            adapter.revalidate(
                                prepared,
                                context,
                                db,
                                target={
                                    "target_type": operation.target_type or "",
                                    "target_id": operation.target_id or "",
                                },
                            )
                        )
                if plan is None or any(p.severity == "error" for p in problems):
                    plan = None
                if plan is None and not batch.parent_batch_id:
                    row.operation_id = None
                if any(p.code in {"auth.forbidden", "auth.unauthenticated"} for p in problems):
                    raise AppError("auth.forbidden")
                if fixed is None:
                    row.normalized_values = json.loads(
                        canonical_json(
                            {
                                **normalized,
                                "_prepared": prepared,
                                "_identity": identity,
                            }
                        )
                    )
                row.warning_count = sum(p.severity == "warning" for p in problems)
                row.error_count = sum(p.severity == "error" for p in problems)
                row.validation_status = "invalid" if row.error_count else "valid"
                row.planned_action = plan.action if plan is not None else "conflict"
                row.validation_version = version
                row.updated_at = now
                for problem in problems:
                    self._issue(db, batch, row, version, problem, now)
            db.flush()
            cp["next_row_no"] = rows[-1].source_row_no + 1 if rows else cp["next_row_no"]
            done = len(rows) < CHUNK_ROWS
            processed = records.validated_count(db, batch.id, version)
            now = utc_now()
            advance_checkpoint(
                db,
                lease,
                now=now,
                checkpoint=cp,
                progress_done=processed,
                progress_total=batch.total_rows,
            )
            if done:
                require_permissions(
                    batch_permissions(db, batch, definition, adapter), context.permissions
                )
                self._publish_preview(db, batch, version, now)
                complete_task(db, lease, now=utc_now())
            else:
                reschedule_task(db, lease, now=utc_now(), next_run_at=now)
            db.commit()

    def _publish_preview(
        self, db: Session, batch: ImportBatch, version: int, now: datetime
    ) -> None:
        # Resolve duplicate natural keys in SQL; raw personal data never enters diagnostics.
        duplicate_rows = records.duplicate_natural_key_rows(db, batch.id, chunk_size=CHUNK_ROWS)
        for index, row in enumerate(duplicate_rows):
            self._issue(
                db,
                batch,
                row,
                version,
                ImportProblem("import.duplicate_in_file", "文件内存在重复业务标识"),
                now,
            )
            row.validation_status, row.planned_action = "invalid", "conflict"
            if batch.parent_batch_id is None:
                row.operation_id = None
            row.error_count += 1
            if index % CHUNK_ROWS == CHUNK_ROWS - 1:
                db.flush()
        control.recalculate(db, batch)
        # A streamed digest binds ordered row identities/results without retaining all row values.
        digest = hashlib.sha256(
            canonical_json(
                {
                    "batch_id": batch.id,
                    "version": version,
                    "template_config_hash": batch.template_config_hash,
                    "scope": batch.scope_snapshot,
                }
            )
        )
        facts = records.preview_facts(db, batch.id, chunk_size=CHUNK_ROWS)
        for fact in facts:
            digest.update(canonical_json(list(fact)))
        batch.preview_version = version
        batch.preview_fingerprint = digest.hexdigest()
        batch.preview_expires_at = min(now + timedelta(hours=24), batch.retention_until)
        validate_transition(batch.status, "preview_ready")
        batch.status = "preview_ready"
        batch.last_error_code = None
        batch.updated_at = now
        batch.row_version += 1
        control.event(db, batch, f"preview:{version}", "preview_ready", now)

    def _apply(self, lease: TaskLease) -> None:
        with self.factory() as db:
            batch, _, definition, context = self._guard(db, lease)
            adapter = cast(ImportAdapter, self.registry.get_adapter(definition.adapter_key))
            required = batch_permissions(db, batch, definition, adapter)
            require_permissions(required, context.permissions)
        for _ in range(CHUNK_ROWS):
            row_id: str | None = None
            try:
                with self.factory() as db:
                    batch, task, definition, context = self._guard(db, lease)
                    require_permissions(required, context.permissions)
                    now = utc_now()
                    if self._cancel(db, batch, lease, now):
                        db.commit()
                        return
                    cp = dict(task.checkpoint)
                    if (
                        now >= batch.retention_until
                        and batch.uncertain_rows == 0
                        and batch.last_error_code == "import.result_uncertain"
                    ):
                        self._expire_recovery(db, batch, lease, now)
                        db.commit()
                        return
                    if (
                        cp["source_preview_version"] != batch.preview_version
                        or batch.confirmed_at is None
                        or batch.apply_policy is None
                    ):
                        raise ValueError("import.preview_stale")
                    row = records.next_pending_row(db, batch.id, cp["next_row_no"])
                    if row is None:
                        self._finish(db, batch, lease, now)
                        db.commit()
                        return
                    row_id = row.id
                    if row.operation_id is None or row.normalized_values is None:
                        raise ValueError("import.operation_identity_mismatch")
                    operation = get_operation(db, row.operation_id, lock=True)
                    if (
                        operation is None
                        or operation.property_company_id != batch.property_company_id
                    ):
                        raise ValueError("import.operation_identity_mismatch")
                    adapter = cast(ImportAdapter, self.registry.get_adapter(definition.adapter_key))
                    prepared = prepared_values(row.normalized_values)
                    if prepared is None:
                        raise ValueError("import.operation_identity_mismatch")
                    source = source_values(row.normalized_values)
                    require_permissions(
                        adapter.required_permissions(source, prepared), context.permissions
                    )
                    plan = adapter.plan(prepared)
                    if (
                        plan.operation_type != operation.operation_type
                        or (plan.input_fingerprint or fingerprint(prepared))
                        != operation.input_fingerprint
                        or operation_key(
                            batch.property_company_id,
                            batch.template_key,
                            plan.operation_type or "",
                            plan.natural_key or {},
                            plan.input_fingerprint or fingerprint(prepared),
                        )
                        != operation.operation_key
                    ):
                        raise ValueError("import.operation_identity_mismatch")
                    result: Mapping[str, Any] | None
                    succeeded = operation.status in {"succeeded", "skipped"}
                    uncertain = not succeeded and (
                        operation.status == "uncertain" or row.execution_status == "uncertain"
                    )
                    problems = (
                        []
                        if uncertain
                        else list(
                            adapter.revalidate(
                                prepared,
                                context,
                                db,
                                target={
                                    "target_type": operation.target_type or "",
                                    "target_id": operation.target_id or "",
                                }
                                if succeeded
                                else None,
                            )
                        )
                    )
                    for problem in problems:
                        if problem.code in {"auth.forbidden", "auth.unauthenticated"}:
                            raise AppError("auth.forbidden")
                        if problem.code == "import.scope_mismatch":
                            raise ValueError("import.scope_mismatch")
                        self._issue(
                            db, batch, row, batch.preview_version, problem, now, phase="apply"
                        )
                    if any(problem.severity == "error" for problem in problems):
                        row.execution_status, row.result_at = "failed", now
                        if not succeeded:
                            operation.status, operation.processed_at = "failed", now
                        result = None
                    elif succeeded:
                        result = {
                            "status": "skipped",
                            "target_type": operation.target_type,
                            "target_id": operation.target_id,
                        }
                    elif uncertain:
                        result = adapter.resolve_operation(
                            operation.operation_key, prepared, context, db
                        )
                        if not result:
                            self._block_unknown(db, batch, row, operation, lease, now)
                            db.commit()
                            return
                    else:
                        operation.status = "running"
                        operation.attempt_count += 1
                        operation.last_attempt_at = now
                        try:
                            with db.begin_nested():
                                result = dict(
                                    adapter.execute(
                                        replace(
                                            plan,
                                            values={
                                                **plan.values,
                                                "_operation_key": operation.operation_key,
                                            },
                                        ),
                                        context,
                                        db,
                                    )
                                )
                        except ImportExecutionFailure as error:
                            operation.status = "failed"
                            operation.processed_at = now
                            row.execution_status, row.result_at = "failed", now
                            problem_code = error.code
                            if error.retryable:
                                problem_code = "import.system_error"
                            elif problem_code == "import.system_error":
                                problem_code = "import.execution_failed"
                            self._issue(
                                db,
                                batch,
                                row,
                                batch.preview_version,
                                ImportProblem(
                                    problem_code,
                                    "暂时无法执行，可重试"
                                    if error.retryable
                                    else "执行失败，不能自动重试",
                                ),
                                now,
                                phase="apply",
                            )
                            result = None
                        except ImportOutcomeUnknown:
                            self._block_unknown(db, batch, row, operation, lease, now)
                            db.commit()
                            return
                        except IntegrityError as error:
                            if getattr(error.orig, "sqlstate", None) != "23505":
                                raise
                            operation.status, operation.processed_at = "failed", now
                            row.execution_status, row.result_at = "failed", now
                            self._issue(
                                db,
                                batch,
                                row,
                                batch.preview_version,
                                ImportProblem("import.conflict", "业务唯一性冲突，请重新核对"),
                                now,
                                phase="apply",
                            )
                            result = None
                    if result is not None:
                        self._save_result(row, operation, result, now)
                    row.updated_at = now
                    if not succeeded:
                        operation.updated_at = now
                    batch.started_at = batch.started_at or now
                    batch.updated_at = now
                    batch.row_version += 1
                    control.recalculate(db, batch)
                    if batch.status == "blocked" and batch.uncertain_rows == 0:
                        if now >= batch.retention_until:
                            self._expire_recovery(db, batch, lease, utc_now())
                            db.commit()
                            return
                        validate_transition(batch.status, "executing")
                        batch.status = "executing"
                    cp["next_row_no"] = row.source_row_no + 1
                    require_current_lease(db, lease, now=utc_now())
                    advance_checkpoint(
                        db,
                        lease,
                        now=utc_now(),
                        checkpoint=cp,
                        progress_done=batch.processed_rows,
                        progress_total=batch.total_rows,
                    )
                    db.commit()
            except DBAPIError as error:
                if error.connection_invalidated and row_id is not None:
                    self._recover_commit(lease, row_id)
                    return
                raise
        with self.factory() as db:
            batch, _, _, _ = self._guard(db, lease)
            now = utc_now()
            reschedule_task(db, lease, now=utc_now(), next_run_at=now)
            db.commit()

    @staticmethod
    def _save_result(
        row: ImportRow, operation: ImportOperation, result: Mapping[str, Any], now: datetime
    ) -> None:
        status = result.get("status")
        if status not in {"created", "skipped"}:
            raise ValueError("import.adapter_result_invalid")
        target_type, target_id = result.get("target_type"), result.get("target_id")
        if not isinstance(target_type, str) or not isinstance(target_id, str):
            raise ValueError("import.adapter_result_invalid")
        if operation.status not in {"succeeded", "skipped"}:
            operation.status = "succeeded" if status == "created" else "skipped"
            operation.target_type, operation.target_id = target_type, target_id
            operation.processed_at = now
        elif (target_type, target_id) != (operation.target_type, operation.target_id):
            raise ValueError("import.operation_identity_mismatch")
        row.execution_status, row.result_at = status, now

    @staticmethod
    def _block_unknown(
        db: Session,
        batch: ImportBatch,
        row: ImportRow,
        operation: ImportOperation,
        lease: TaskLease,
        now: datetime,
    ) -> None:
        operation.status, operation.processed_at, operation.updated_at = "uncertain", now, now
        row.execution_status, row.result_at, row.updated_at = "uncertain", now, now
        batch.status, batch.finished_at = "blocked", None
        batch.last_error_code = "import.result_uncertain"
        batch.row_version += 1
        control.recalculate(db, batch)
        pause_task(db, lease, now=now, error_code="import.result_uncertain")
        control.event(
            db,
            batch,
            f"uncertain:{row.id}",
            "blocked",
            now,
            task_id=lease.id,
            task_attempt=lease.attempt_count,
        )

    def _recover_commit(self, lease: TaskLease, row_id: str) -> None:
        with self.factory() as db:
            batch, _, _, _ = self._guard(db, lease)
            row = records.row_by_id(db, row_id)
            if row is None or row.operation_id is None:
                raise ValueError("import.operation_identity_mismatch")
            operation = get_operation(db, row.operation_id, lock=True)
            if operation is None:
                raise ValueError("import.operation_identity_mismatch")
            now = utc_now()
            if operation.status in {"succeeded", "skipped"} or row.execution_status in {
                "created",
                "skipped",
                "failed",
                "excluded",
                "cancelled",
            }:
                # Resume this row; a known shared success may predate its transaction.
                reschedule_task(db, lease, now=utc_now(), next_run_at=now)
            else:
                self._block_unknown(db, batch, row, operation, lease, now)
            db.commit()

    @staticmethod
    def _expire_recovery(db: Session, batch: ImportBatch, lease: TaskLease, now: datetime) -> None:
        # Expiry never creates replacement operations or erases a committed result.
        records.cancel_pending_rows(db, batch.id, now=now)
        control.recalculate(db, batch)
        if batch.uncertain_rows:
            raise ValueError("import.result_uncertain")
        validate_transition(batch.status, "expired")
        batch.status, batch.finished_at, batch.updated_at = "expired", now, now
        batch.last_error_code = "import.data_expired"
        batch.row_version += 1
        complete_task(db, lease, now=utc_now())
        control.event(
            db,
            batch,
            "recovery_expired",
            "expired",
            now,
            task_id=lease.id,
            task_attempt=lease.attempt_count,
        )

    @staticmethod
    def _finish(db: Session, batch: ImportBatch, lease: TaskLease, now: datetime) -> None:
        control.recalculate(db, batch)
        if batch.uncertain_rows:
            batch.status, batch.finished_at = "blocked", None
            batch.last_error_code = "import.result_uncertain"
            pause_task(db, lease, now=now, error_code="import.result_uncertain")
            return
        target = (
            "partial_failed"
            if batch.failed_rows and batch.created_rows + batch.skipped_rows
            else "failed"
            if batch.failed_rows
            else "completed"
        )
        validate_transition(batch.status, target, uncertain_rows=batch.uncertain_rows)
        batch.status = target
        batch.finished_at, batch.updated_at = now, now
        batch.last_error_code = None
        batch.row_version += 1
        complete_task(db, lease, now=utc_now())
        control.event(
            db,
            batch,
            "apply_completed",
            "completed",
            now,
            task_id=lease.id,
            task_attempt=lease.attempt_count,
        )

    def _pause(self, lease: TaskLease, code: str) -> None:
        with self.factory() as db:
            batch = get_batch(db, lease.batch_id, lock=True)
            if batch is None:
                raise LeaseLost
            require_current_lease(db, lease, now=utc_now())
            now = utc_now()
            pause_task(db, lease, now=now, error_code=code)
            if lease.phase != "artifact":
                batch.status, batch.finished_at = "blocked", None
                batch.last_error_code, batch.updated_at = code, now
                batch.row_version += 1
            control.event(
                db,
                batch,
                f"paused:{lease.id}:{lease.attempt_count}",
                "blocked",
                now,
                task_id=lease.id,
                task_attempt=lease.attempt_count,
                metadata={"error_code": code},
            )
            db.commit()

    def _parse_error(self, lease: TaskLease, code: str) -> None:
        with self.factory() as db:
            batch = get_batch(db, lease.batch_id, lock=True)
            if batch is None:
                raise LeaseLost
            require_current_lease(db, lease, now=utc_now())
            now = utc_now()
            add_issue(
                db,
                batch_id=batch.id,
                preview_version=0,
                phase="parse",
                severity="error",
                code=code,
                message="文件结构或内容不符合模板要求",
                created_at=now,
            )
            batch.status, batch.finished_at = "failed", now
            batch.last_error_code, batch.updated_at = code, now
            batch.row_version += 1
            complete_task(db, lease, now=utc_now())
            control.event(
                db,
                batch,
                "parse_failed",
                "failed",
                now,
                task_id=lease.id,
                task_attempt=lease.attempt_count,
            )
            db.commit()
