from datetime import timedelta
from typing import Any, cast

from backend_app.core.errors import AppError
from backend_app.domain.imports.registry import ImportDefinition
from backend_app.integrations.import_files.errors import ImportFileError
from backend_app.models.admin import utc_now
from backend_app.models.imports import ImportBatch
from backend_app.repositories.admin import AdminRepository
from backend_app.repositories.imports import queries
from backend_app.schemas.mappers import imports as view
from backend_app.services.contracts.admin import AdminContext
from backend_app.services.imports import presentation
from backend_app.services.imports.access import ImportAccess
from backend_app.services.imports.artifacts import FileDownload
from backend_app.services.imports.permissions import batch_permissions, prepared_values
from backend_app.services.worker.imports.adapters.base import ImportAdapter


class ImportQueries:
    def __init__(self, access: ImportAccess) -> None:
        self.access = access

    def _batch_definition(
        self, batch: ImportBatch, permissions: frozenset[str]
    ) -> ImportDefinition | None:
        try:
            return self.access.definition(
                batch.template_key,
                batch.template_version_no,
                permissions,
                batch.template_config_hash,
                for_write=False,
            )
        except AppError as error:
            if error.code in {"import.template_unavailable", "import.template_drift"}:
                return None
            raise

    def _batch_view(
        self, ctx: AdminContext, batch: ImportBatch, permissions: frozenset[str]
    ) -> dict[str, Any]:
        from backend_app.repositories.imports.queries import excluded_count

        now = utc_now()
        tasks = queries.tasks(self.access.db, batch.id)
        source = queries.source(self.access.db, batch.id)
        definition = self._batch_definition(batch, permissions)
        retryable = (
            queries.retryable_count(self.access.db, batch)
            if definition and now < batch.retention_until
            else 0
        )
        active = any(t.status in {"ready", "running"} for t in tasks)
        paused = any(t.status == "paused" and t.phase != "artifact" for t in tasks)
        actions = []
        write_allowed = False
        if definition is not None and set(definition.required_permissions) <= permissions:
            adapter = cast(ImportAdapter, self.access.registry.get_adapter(definition.adapter_key))
            write_allowed = (
                batch_permissions(self.access.db, batch, definition, adapter) <= permissions
            )
        if not write_allowed:
            retryable = 0

        def allow(action: str, permission: str, condition: bool) -> None:
            if condition and f"{self.access.prefix}.import.{permission}" in permissions:
                actions.append(action)

        alive = now < batch.retention_until
        allow(
            "upload_source_file",
            "upload",
            write_allowed
            and alive
            and (batch.status == "draft")
            and (now < batch.created_at + timedelta(hours=24)),
        )
        allow(
            "precheck",
            "precheck",
            write_allowed
            and alive
            and (batch.confirmed_at is None)
            and (batch.status in {"preview_ready", "blocked"})
            and (not active)
            and (not paused)
            and (batch.uncertain_rows == 0),
        )
        allow(
            "confirm",
            "execute",
            write_allowed
            and alive
            and (batch.status == "preview_ready")
            and (batch.preview_expires_at is not None)
            and (now < batch.preview_expires_at)
            and (not active),
        )
        allow(
            "cancel",
            "cancel",
            alive
            and batch.status not in view.TERMINAL
            and batch.status != "cancel_requested"
            and (not batch.uncertain_rows),
        )
        allow(
            "retry_failed",
            "retry",
            write_allowed and retryable > 0 and batch.status in view.TERMINAL,
        )
        allow(
            "recover",
            "recover",
            write_allowed and (batch.status == "blocked" or paused) and (not active),
        )
        allow(
            "generate_error_file",
            "generate_error_file",
            bool(definition)
            and alive
            and (batch.preview_version > 0)
            and not view.unpublished_input(tasks)
            and (not active)
            and (
                batch.error_rows + batch.warning_rows + batch.failed_rows + batch.uncertain_rows > 0
            ),
        )
        artifact_task = next((t for t in tasks if t.phase == "artifact"), None)
        artifact = queries.error_artifact(self.access.db, batch.id)
        ef = view.error_file(
            batch,
            artifact_task,
            artifact,
            now,
            f"{self.access.prefix}.import.download" in permissions,
        )
        allow("download_error_file", "download", ef["downloadable"])
        creator = AdminRepository(self.access.db, self.access.scope).identity(batch.created_by_id)
        return view.batch_view(
            batch,
            tasks,
            source,
            now=now,
            type_name=definition.name if definition else batch.template_key,
            creator_name=creator.display_name if creator else "管理员",
            next_actions=actions,
            retryable_count=retryable,
            excluded_count=excluded_count(self.access.db, batch.id),
            business_preview=presentation.preview(
                self.access.db, batch, self.access.registry.get_adapter(definition.adapter_key)
            )
            if definition
            and alive
            and batch.preview_version > 0
            and batch.status != "prechecking"
            and not view.unpublished_input(tasks)
            else None,
        )

    def batches(self, ctx: AdminContext, **filters: Any) -> dict[str, Any]:
        _, _, permissions = self.access.authorize(ctx, "read")
        self.access.company_id(ctx, filters.get("property_company_id"))
        if filters.get("scope_id") and (not filters.get("scope_type")):
            raise AppError("VALIDATION_ERROR")
        if (
            filters.get("created_from")
            and filters.get("created_before")
            and (filters["created_before"] <= filters["created_from"])
        ):
            raise AppError("VALIDATION_ERROR")
        items, total = queries.batches(
            self.access.db, self.access.scope, self.access.company_id(ctx, None), filters
        )
        return dict(
            items=[self._batch_view(ctx, b, permissions) for b in items],
            total=total,
            page=filters.get("page") or 1,
            page_size=filters.get("page_size") or 20,
        )

    def batch(self, ctx: AdminContext, batch_id: str) -> dict[str, Any]:
        _, _, permissions = self.access.authorize(ctx, "read")
        batch = self.access.target(ctx, batch_id)
        return self._batch_view(ctx, batch, permissions)

    def _read_rows(self, ctx: AdminContext, batch_id: str) -> tuple[ImportBatch, frozenset[str]]:
        _, _, permissions = self.access.authorize(ctx, "read")
        batch = self.access.target(ctx, batch_id)
        self.access.alive(batch, utc_now())
        if batch.status in {"prechecking", "uploading"} or view.unpublished_input(
            queries.tasks(self.access.db, batch.id)
        ):
            raise AppError("import.batch_state_conflict")
        definition = self.access.definition(
            batch.template_key,
            batch.template_version_no,
            permissions,
            batch.template_config_hash,
            for_write=False,
        )
        return (batch, frozenset(f.key for f in definition.fields if not f.sensitive))

    def rows(self, ctx: AdminContext, batch_id: str, **filters: Any) -> dict[str, Any]:
        batch, fields = self._read_rows(ctx, batch_id)
        rows, total = queries.rows(self.access.db, batch, filters)
        issues = queries.row_issues(self.access.db, batch, [r.id for r in rows])
        definition = self.access.registry.get(
            batch.template_key, batch.template_version_no, batch.template_config_hash
        )
        adapter = self.access.registry.get_adapter(definition.adapter_key)
        return dict(
            items=[
                view.row_view(
                    row,
                    [i for i in issues if i.row_id == row.id],
                    fields,
                    presentation.values(adapter, prepared_values(row.normalized_values)),
                )
                for row in rows
            ],
            total=total,
            page=filters.get("page") or 1,
            page_size=filters.get("page_size") or 20,
        )

    def issues(self, ctx: AdminContext, batch_id: str, **filters: Any) -> dict[str, Any]:
        batch, fields = self._read_rows(ctx, batch_id)
        issues, total = queries.issues(self.access.db, batch, filters)
        retryable = queries.retryable_row_ids(
            self.access.db, batch, [i.row_id for i in issues if i.row_id]
        )
        rows = queries.rows_by_ids(self.access.db, [i.row_id for i in issues if i.row_id])
        return dict(
            items=[
                view.issue_view(
                    i,
                    rows.get(i.row_id or ""),
                    fields,
                    i.row_id in retryable
                    and i.phase == "apply"
                    and (i.code == "import.system_error"),
                )
                for i in issues
            ],
            total=total,
            page=filters.get("page") or 1,
            page_size=filters.get("page_size") or 20,
        )

    def events(self, ctx: AdminContext, batch_id: str, **filters: Any) -> dict[str, Any]:
        _, _, permissions = self.access.authorize(ctx, "read")
        batch = self.access.target(ctx, batch_id)
        self._batch_definition(batch, permissions)
        items, total = queries.events(self.access.db, batch.id, filters)
        return dict(
            items=[
                dict(
                    id=i.id,
                    event_type=i.event_type,
                    phase=i.safe_metadata.get("phase"),
                    message={
                        "created": "已创建导入批次",
                        "task_claimed": "已领取阶段任务",
                        "task_taken_over": "原租约已过期，任务已接管",
                        "source_uploaded": "已上传源文件",
                        "confirmed": "已确认执行",
                        "cancel_requested": "已请求取消",
                        "recovered": "已请求核实与恢复",
                        "error_file_requested": "已请求生成错误文件",
                    }.get(i.event_type, "导入任务状态已更新"),
                    created_at=i.created_at,
                )
                for i in items
            ],
            total=total,
            page=filters.get("page") or 1,
            page_size=filters.get("page_size") or 20,
        )

    def error_file(self, ctx: AdminContext, batch_id: str) -> dict[str, Any]:
        _, _, permissions = self.access.authorize(ctx, "read")
        batch = self.access.target(ctx, batch_id)
        self._batch_definition(batch, permissions)
        task = next(
            (t for t in queries.tasks(self.access.db, batch.id) if t.phase == "artifact"), None
        )
        return view.error_file(
            batch,
            task,
            queries.error_artifact(self.access.db, batch.id),
            utc_now(),
            f"{self.access.prefix}.import.download" in permissions,
        )

    def download_error_file(
        self, ctx: AdminContext, batch_id: str, generation: int, request_id: str
    ) -> FileDownload:
        identity, actor, permissions = self.access.authorize(ctx, "download")
        batch = self.access.target(ctx, batch_id)
        self.access.definition(
            batch.template_key,
            batch.template_version_no,
            permissions,
            batch.template_config_hash,
            for_write=False,
        )
        self.access.check_scope(batch)
        now = utc_now()
        if now >= batch.retention_until:
            raise AppError("import.artifact_expired")
        task = next(
            (t for t in queries.tasks(self.access.db, batch.id) if t.phase == "artifact"), None
        )
        artifact = queries.error_artifact(self.access.db, batch.id, generation)
        state = view.error_file(batch, task, artifact, now, True)
        if artifact and artifact.deleted_at:
            raise AppError("import.artifact_expired")
        if not artifact or state["status"] != "ready" or state["generation"] != generation:
            raise AppError("import.error_file_not_ready")
        key, sha, size, media = (
            artifact.storage_key,
            artifact.sha256,
            artifact.byte_size,
            artifact.media_type,
        )
        identity.audit.record(
            actor=actor,
            action="import.download",
            target_type="import_batch",
            target_id=batch.id,
            request_id=request_id,
            property_company_id=batch.property_company_id,
        )
        self.access.db.commit()
        try:
            self.access.storage.verify(key, expected_sha256=sha, expected_size=size)
            source = self.access.storage.path(key).open("rb")
        except ImportFileError, OSError:
            raise AppError("system.dependency_unavailable") from None
        return FileDownload(
            source,
            f"import-errors-{generation}.csv"
            if media == "text/csv"
            else f"import-errors-{generation}.xlsx",
            media,
            size,
        )
