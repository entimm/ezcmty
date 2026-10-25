from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, BinaryIO

from sqlalchemy.exc import IntegrityError

from backend_app.core.errors import AppError
from backend_app.core.identifiers import new_id
from backend_app.domain.admin.identity import AdminIdentity
from backend_app.domain.imports.fingerprints import fingerprint
from backend_app.integrations.import_files.csv_parser import parse_csv_chunk
from backend_app.integrations.import_files.errors import ImportFileError
from backend_app.integrations.import_files.storage import safe_download_name
from backend_app.integrations.import_files.xlsx_parser import validate_xlsx
from backend_app.models.admin import AdminAccount, utc_now
from backend_app.models.imports import ImportArtifact, ImportBatch, ImportRow
from backend_app.repositories.imports import control, queries
from backend_app.repositories.imports.requests import (
    IdempotencyConflict,
    find_request,
    record_request,
)
from backend_app.schemas import imports as schema
from backend_app.schemas.mappers import imports as view
from backend_app.services.contracts.admin import AdminContext
from backend_app.services.imports.access import ImportAccess


class ImportControlPlane:
    def __init__(self, access: ImportAccess) -> None:
        self.access = access

    def _request_args(
        self, ctx: AdminContext, company_id: str, action: str, key: str, digest: str
    ) -> dict[str, Any]:
        return dict(
            property_company_id=company_id,
            actor_scope=self.access.scope,
            actor_id=ctx.account_id,
            request_scope=action,
            idempotency_key=key,
            request_fingerprint=digest,
        )

    def _previous(self, args: dict[str, Any]) -> dict[str, Any] | None:
        try:
            record = find_request(self.access.db, **args)
        except IdempotencyConflict:
            raise AppError("import.idempotency_conflict") from None
        return record.response_body if record else None

    def _commit(
        self,
        ctx: AdminContext,
        actor: AdminAccount,
        identity: AdminIdentity,
        batch: ImportBatch,
        args: dict[str, Any],
        response: dict[str, Any],
        status: int,
        action: str,
        request_id: str,
        now: datetime,
    ) -> dict[str, Any]:
        try:
            identity.audit.record(
                actor=actor,
                action=f"import.{action}",
                target_type="import_batch",
                target_id=batch.id,
                property_company_id=batch.property_company_id,
                request_id=request_id,
            )
            record_request(
                self.access.db,
                **args,
                batch_id=batch.id,
                http_status=status,
                response_body=response,
                now=now,
            )
            self.access.db.commit()
            return response
        except IntegrityError:
            self.access.db.rollback()
            _, _, current_permissions = self.access.authorize(
                ctx,
            )
            previous = self._previous(args)
            if previous is None:
                raise
            replay_batch = self.access.target(
                ctx, str(previous.get("batch_id") or previous.get("source_batch_id"))
            )
            self.access.check_scope(replay_batch)
            self.access.definition(
                replay_batch.template_key,
                replay_batch.template_version_no,
                current_permissions,
                replay_batch.template_config_hash,
                for_write=action != "error_file",
            )
            if action in {"precheck", "confirm", "retry_failed", "recover"}:
                self.access.check_business_permissions(replay_batch, current_permissions)
            return previous

    def create(
        self, ctx: AdminContext, data: schema.ImportBatchCreate, *, key: str, request_id: str
    ) -> dict[str, Any]:
        identity, actor, permissions = self.access.authorize(ctx)
        company_id = self.access.company_id(ctx, data.property_company_id, creating=True)
        if company_id is None:
            raise AppError("VALIDATION_ERROR")
        definition = self.access.definition(data.import_type, data.template_version_no, permissions)
        company = self.access.repo.company(company_id)
        if company is None:
            raise AppError("resource.not_found")
        if not company.enabled:
            raise AppError("auth.forbidden")
        if data.scope.type not in definition.allowed_scope_types:
            raise AppError("VALIDATION_ERROR")
        community = None
        if data.scope.type == "company":
            if data.scope.id != company_id:
                raise AppError("VALIDATION_ERROR")
            name = company.name
        else:
            community = self.access.repo.community(data.scope.id, company_scope_id=company_id)
            if community is None:
                raise AppError("resource.not_found")
            if not community.enabled:
                raise AppError("auth.forbidden")
            name = community.name
        digest = fingerprint(
            dict(
                import_type=data.import_type,
                template_version_no=data.template_version_no,
                scope=data.scope.model_dump(),
                mode=data.mode,
                property_company_id=company_id,
            )
        )
        args = self._request_args(ctx, company_id, "create", key, digest)
        previous = self._previous(args)
        if previous:
            return previous
        if not definition.available_for_new_batches:
            raise AppError("import.template_unavailable")
        now = utc_now()
        batch = ImportBatch(
            id=new_id(),
            property_company_id=company_id,
            community_id=community.id if community else None,
            scope_type=data.scope.type,
            scope_snapshot=dict(type=data.scope.type, id=data.scope.id, name=name),
            template_key=definition.key,
            template_version_no=definition.version_no,
            template_config_hash=definition.config_hash,
            created_by_scope=self.access.scope,
            created_by_id=actor.id,
            request_id=request_id,
            retention_until=now + timedelta(days=30),
            created_at=now,
            updated_at=now,
        )
        self.access.db.add(batch)
        self.access.db.flush()
        control.event(
            self.access.db,
            batch,
            "created",
            "created",
            now,
            actor_scope=self.access.scope,
            actor_id=actor.id,
        )
        response = view.action(batch, [], None)
        return self._commit(
            ctx, actor, identity, batch, args, response, 201, "create", request_id, now
        )

    def upload(
        self,
        ctx: AdminContext,
        *,
        batch_id: str,
        key: str,
        request_id: str,
        file: BinaryIO,
        filename: str,
    ) -> dict[str, Any]:
        _, _, permissions = self.access.authorize(ctx)
        batch = self.access.target(ctx, batch_id)
        self.access.check_scope(batch)
        self.access.definition(
            batch.template_key,
            batch.template_version_no,
            permissions,
            batch.template_config_hash,
        )
        company_id = batch.property_company_id
        retention = batch.retention_until
        self.access.db.rollback()
        extension = Path(filename).suffix.lower()
        if extension not in {".csv", ".xlsx"}:
            raise AppError("import.file_type_unsupported")
        import hashlib

        digest_file = hashlib.sha256()
        size = 0
        for chunk in iter(lambda: file.read(65536), b""):
            size += len(chunk)
            if size > 10485760:
                raise AppError("import.file_too_large")
            digest_file.update(chunk)
        file.seek(0)
        sha = digest_file.hexdigest()
        args = self._request_args(
            ctx,
            company_id,
            f"source_file:{batch_id}",
            key,
            fingerprint(dict(batch_id=batch_id, sha256=sha)),
        )
        _, _, permissions = self.access.authorize(ctx)
        batch = self.access.target(ctx, batch_id, lock=True)
        self.access.check_scope(batch)
        self.access.definition(
            batch.template_key, batch.template_version_no, permissions, batch.template_config_hash
        )
        previous = self._previous(args)
        if previous:
            return previous
        self.access.alive(batch, utc_now())
        if (
            batch.status != "draft"
            or queries.source(self.access.db, batch.id)
            or utc_now() >= batch.created_at + timedelta(hours=24)
        ):
            raise AppError("import.batch_state_conflict")
        self.access.db.rollback()
        storage_key = f"{company_id}/{batch_id}/source/{sha}{extension}"
        try:
            stored = self.access.storage.write(storage_key, file)
            if extension == ".xlsx":
                validate_xlsx(self.access.storage.path(storage_key))
            else:
                parse_csv_chunk(self.access.storage.path(storage_key), limit=1)
        except ImportFileError as error:
            raise AppError(error.code) from None
        except OSError:
            raise AppError("system.dependency_unavailable") from None
        identity, actor, permissions = self.access.authorize(ctx)
        batch = self.access.target(ctx, batch_id, lock=True)
        self.access.check_scope(batch)
        self.access.definition(
            batch.template_key, batch.template_version_no, permissions, batch.template_config_hash
        )
        args = self._request_args(
            ctx,
            company_id,
            f"source_file:{batch_id}",
            key,
            fingerprint(dict(batch_id=batch_id, sha256=sha)),
        )
        previous = self._previous(args)
        if previous:
            return previous
        now = utc_now()
        self.access.alive(batch, now)
        if (
            batch.status != "draft"
            or queries.source(self.access.db, batch.id)
            or now >= batch.created_at + timedelta(hours=24)
        ):
            raise AppError("import.batch_state_conflict")
        artifact = ImportArtifact(
            batch_id=batch.id,
            artifact_kind="source",
            generation=1,
            storage_key=stored.key,
            original_filename=safe_download_name(filename),
            media_type="text/csv"
            if extension == ".csv"
            else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            sha256=sha,
            byte_size=stored.byte_size,
            expires_at=retention,
            created_at=now,
            updated_at=now,
        )
        self.access.db.add(artifact)
        self.access.db.flush()
        definition = self.access.registry.get(
            batch.template_key, batch.template_version_no, batch.template_config_hash
        )
        cursor = (
            dict(kind="csv_record", next_byte_offset=0, next_row_no=1)
            if extension == ".csv"
            else dict(kind="xlsx_row", sheet_name=definition.sheet_name, next_row_no=2)
        )
        control.task(
            self.access.db,
            batch,
            "parse",
            dict(schema_version=1, source_artifact_generation=1, cursor=cursor),
            now,
        )
        batch.status = "prechecking"
        batch.updated_at = now
        batch.row_version += 1
        control.event(
            self.access.db,
            batch,
            "source_uploaded",
            "source_uploaded",
            now,
            actor_scope=self.access.scope,
            actor_id=actor.id,
        )
        return self._commit(
            ctx,
            actor,
            identity,
            batch,
            args,
            view.action(batch, queries.tasks(self.access.db, batch.id), artifact),
            202,
            "source_file",
            request_id,
            now,
        )

    def mutate(
        self,
        ctx: AdminContext,
        batch_id: str,
        action: str,
        data: dict[str, Any],
        key: str,
        request_id: str,
    ) -> dict[str, Any]:
        identity, actor, permissions = self.access.authorize(ctx)
        batch = self.access.target(ctx, batch_id, lock=True)
        self.access.check_scope(batch)
        self.access.definition(
            batch.template_key,
            batch.template_version_no,
            permissions,
            batch.template_config_hash,
            for_write=action != "error_file",
        )
        if action in {"precheck", "confirm", "retry_failed", "recover"}:
            self.access.check_business_permissions(batch, permissions)
        args = self._request_args(
            ctx,
            batch.property_company_id,
            f"{action}:{batch_id}",
            key,
            fingerprint(dict(batch_id=batch_id, **data)),
        )
        previous = self._previous(args)
        if previous:
            return previous
        now = utc_now()
        if action == "cancel" and now >= batch.retention_until:
            raise AppError("import.batch_state_conflict")
        if action not in {"recover", "cancel"}:
            self.access.alive(batch, now)
        tasks = queries.tasks(self.access.db, batch.id)
        active = any(t.status in {"ready", "running"} for t in tasks)
        source = queries.source(self.access.db, batch.id)
        result: dict[str, Any] | None = None
        status = 202
        if action == "precheck":
            if data["preview_version"] != batch.preview_version:
                raise AppError("import.preview_stale")
            parse = next((t for t in tasks if t.phase == "parse"), None)
            if (
                batch.confirmed_at
                or batch.status in view.TERMINAL
                or any(t.phase != "artifact" and t.status == "paused" for t in tasks)
                or active
                or batch.uncertain_rows
                or (not batch.parent_batch_id and (parse is None or parse.status != "completed"))
            ):
                raise AppError("import.batch_state_conflict")
            control.task(
                self.access.db,
                batch,
                "precheck",
                dict(
                    schema_version=1,
                    target_preview_version=batch.preview_version + 1,
                    next_row_no=1,
                ),
                now,
            )
            batch.status = "prechecking"
            batch.last_error_code = None
        elif action == "confirm":
            if batch.status != "preview_ready" or active or batch.confirmed_at:
                raise AppError("import.batch_state_conflict")
            if (
                data["preview_version"] != batch.preview_version
                or data["preview_fingerprint"] != batch.preview_fingerprint
                or batch.preview_expires_at is None
                or (now >= batch.preview_expires_at)
            ):
                raise AppError("import.preview_stale")
            if queries.has_blocking_issue(self.access.db, batch) or (
                data["apply_policy"] == "all_rows" and batch.error_rows
            ):
                raise AppError("import.batch_state_conflict")
            if (
                queries.selected_count(self.access.db, batch, bool(data["include_warning_rows"]))
                == 0
            ):
                raise AppError("import.no_executable_rows")
            control.exclude_rows(self.access.db, batch, bool(data["include_warning_rows"]), now)
            batch.apply_policy = data["apply_policy"]
            batch.include_warning_rows = data["include_warning_rows"]
            batch.confirmed_at = now
            batch.status = "executing"
            control.task(
                self.access.db,
                batch,
                "apply",
                dict(schema_version=1, source_preview_version=batch.preview_version, next_row_no=1),
                now,
            )
            control.recalculate(self.access.db, batch)
        elif action == "cancel":
            if batch.status in view.TERMINAL or batch.uncertain_rows:
                raise AppError("import.batch_state_conflict")
            batch.status = "cancel_requested"
            batch.cancel_requested_at = now
            if not any(t.status == "running" and t.phase != "artifact" for t in tasks):
                control.cancel_remaining(self.access.db, batch, now)
        elif action == "retry_failed":
            if batch.status not in view.TERMINAL or batch.uncertain_rows or active:
                raise AppError("import.batch_state_conflict")
            if queries.retryable_count(self.access.db, batch) == 0:
                raise AppError("import.no_retryable_rows")
            new = ImportBatch(
                id=new_id(),
                property_company_id=batch.property_company_id,
                community_id=batch.community_id,
                scope_type=batch.scope_type,
                scope_snapshot=batch.scope_snapshot,
                template_key=batch.template_key,
                template_version_no=batch.template_version_no,
                template_config_hash=batch.template_config_hash,
                parent_batch_id=batch.id,
                created_by_scope=self.access.scope,
                created_by_id=actor.id,
                request_id=request_id,
                status="prechecking",
                retention_until=batch.retention_until,
                created_at=now,
                updated_at=now,
            )
            self.access.db.add(new)
            self.access.db.flush()
            selected_rows = 0
            for row in queries.iter_retryable_rows(self.access.db, batch):
                selected_rows += 1
                self.access.db.add(
                    ImportRow(
                        batch_id=new.id,
                        source_row_no=row.source_row_no,
                        raw_values=row.raw_values,
                        normalized_values=row.normalized_values,
                        operation_id=row.operation_id,
                        created_at=now,
                        updated_at=now,
                    )
                )
                if selected_rows % 200 == 0:
                    self.access.db.flush()
            if selected_rows == 0:
                raise AppError("import.no_retryable_rows")
            self.access.db.flush()
            control.recalculate(self.access.db, new)
            control.task(
                self.access.db,
                new,
                "precheck",
                dict(schema_version=1, target_preview_version=1, next_row_no=1),
                now,
            )
            control.event(
                self.access.db,
                new,
                "created",
                "created",
                now,
                actor_scope=self.access.scope,
                actor_id=actor.id,
            )
            result = dict(
                source_batch_id=batch.id,
                selected_rows=selected_rows,
                batch=view.action(new, queries.tasks(self.access.db, new.id), None),
            )
            status = 201
        elif action == "recover":
            candidates = [t for t in tasks if t.phase != "artifact" and t.status == "paused"]
            if active or not candidates or (batch.status != "blocked" and (not candidates)):
                raise AppError("import.recovery_not_allowed")
            task = candidates[0]
            from backend_app.domain.imports.checkpoint import validate_checkpoint

            try:
                validate_checkpoint(task.phase, task.checkpoint)
            except ValueError:
                raise AppError("import.recovery_not_allowed") from None
            if now >= batch.retention_until and (not batch.uncertain_rows):
                raise AppError("import.recovery_not_allowed")
            task.status = "ready"
            task.next_run_at = now
            task.last_error_code = None
            task.lease_expires_at = None
            task.completed_at = None
            task.updated_at = now
            batch.status = (
                "blocked"
                if batch.uncertain_rows
                else "executing"
                if batch.confirmed_at
                else "prechecking"
            )
        elif action == "error_file":
            if batch.preview_version != data["preview_version"]:
                raise AppError("import.preview_stale")
            if (
                batch.preview_version == 0
                or view.unpublished_input(tasks)
                or active
                or any(t.phase == "artifact" and t.status == "running" for t in tasks)
            ):
                raise AppError("import.batch_state_conflict")
            if not queries.has_export_rows(self.access.db, batch):
                raise AppError("import.no_error_rows")
            old = next((t for t in tasks if t.phase == "artifact"), None)
            artifact = queries.error_artifact(self.access.db, batch.id)
            generation = (
                max(
                    artifact.generation if artifact else 0,
                    old.checkpoint.get("output_generation", 0) if old else 0,
                )
                + 1
            )
            task = control.task(
                self.access.db,
                batch,
                "artifact",
                dict(
                    schema_version=1,
                    source_preview_version=batch.preview_version,
                    source_batch_row_version=batch.row_version,
                    output_generation=generation,
                    next_row_no=1,
                    next_part_no=1,
                ),
                now,
            )
            control.event(
                self.access.db,
                batch,
                f"error-file:{generation}",
                "error_file_requested",
                now,
                actor_scope=self.access.scope,
                actor_id=actor.id,
                metadata={"generation": generation, "format": data["format"]},
            )
            result = dict(
                batch_id=batch.id,
                status="queued",
                generation=generation,
                source_preview_version=batch.preview_version,
                task=view.task_view(task),
            )
        else:
            raise AppError("VALIDATION_ERROR")
        if action not in {"error_file", "retry_failed"}:
            batch.row_version += 1
            batch.updated_at = now
        control.event(
            self.access.db,
            batch,
            f"{action}:{fingerprint(key)}",
            {"confirm": "confirmed", "cancel": "cancel_requested", "recover": "recovered"}.get(
                action, action
            ),
            now,
            actor_scope=self.access.scope,
            actor_id=actor.id,
        )
        self.access.db.flush()
        if result is None:
            result = view.action(batch, queries.tasks(self.access.db, batch.id), source)
        return self._commit(
            ctx, actor, identity, batch, args, result, status, action, request_id, now
        )
