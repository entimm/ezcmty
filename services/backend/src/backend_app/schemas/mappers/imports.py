"""Pure white-list projections of already loaded import facts."""

from datetime import datetime
from typing import Any

from backend_app.models.imports import (
    ImportArtifact,
    ImportBatch,
    ImportIssue,
    ImportRow,
    ImportTask,
)

TERMINAL = frozenset({"completed", "partial_failed", "failed", "cancelled", "expired"})


def task_view(task: ImportTask | None, *, progress: bool = False) -> dict[str, Any] | None:
    if task is None:
        return None
    result: dict[str, Any] = {"id": task.id, "phase": task.phase, "status": task.status}
    if progress:
        result.update(
            progress_done=task.progress_done,
            progress_total=task.progress_total or None,
            updated_at=task.updated_at,
            last_error_code=task.last_error_code,
        )
    return result


def active_task(tasks: list[ImportTask]) -> ImportTask | None:
    return next(
        (t for t in tasks if t.phase != "artifact" and t.status in {"ready", "running", "paused"}),
        None,
    )


def unpublished_input(tasks: list[ImportTask]) -> bool:
    return any(
        task.phase in {"parse", "precheck"} and task.status in {"ready", "running", "paused"}
        for task in tasks
    )


def phase(batch: ImportBatch, tasks: list[ImportTask]) -> str:
    if batch.status in TERMINAL:
        return "finished"
    if batch.status == "cancel_requested":
        return "cancelling"
    if batch.status == "draft":
        return "awaiting_source_file"
    if batch.status == "uploading":
        return "uploading"
    if batch.status == "preview_ready":
        return "awaiting_confirmation"
    task = active_task(tasks)
    if task:
        return task.phase + ("_queued" if task.status == "ready" else "")
    return "recovery" if batch.status == "blocked" else "precheck_queued"


def action(
    batch: ImportBatch, tasks: list[ImportTask], source: ImportArtifact | None
) -> dict[str, Any]:
    return dict(
        batch_id=batch.id,
        status=batch.status,
        phase=phase(batch, tasks),
        preview_version=batch.preview_version,
        active_task=task_view(active_task(tasks)),
        source_artifact=None
        if source is None
        else dict(id=source.id, size_bytes=source.byte_size, sha256=source.sha256),
    )


def error_file(
    batch: ImportBatch,
    task: ImportTask | None,
    artifact: ImportArtifact | None,
    now: datetime,
    can_download: bool,
) -> dict[str, Any]:
    cp = task.checkpoint if task else {}
    generation = cp.get("output_generation")
    status = "not_generated"
    if task:
        status = {
            "ready": "queued",
            "running": "generating",
            "paused": "failed",
            "completed": "ready",
            "cancelled": "failed",
        }[task.status]
        if (
            cp.get("source_preview_version") != batch.preview_version
            or cp.get("source_batch_row_version") != batch.row_version
        ):
            status = "stale"
        elif now >= batch.retention_until or (artifact and artifact.deleted_at):
            status = "expired"
        elif status == "ready" and (not artifact or artifact.generation != generation):
            status = "failed"
    ready = status == "ready"
    return dict(
        batch_id=batch.id,
        status=status,
        generation=generation,
        source_preview_version=cp.get("source_preview_version"),
        format=("csv" if artifact.media_type == "text/csv" else "xlsx") if artifact else None,
        task=task_view(task, progress=True),
        file_name=(
            f"import-errors-{generation}.csv"
            if artifact and artifact.media_type == "text/csv"
            else f"import-errors-{generation}.xlsx"
        )
        if ready
        else None,
        media_type=artifact.media_type if ready and artifact else None,
        size_bytes=artifact.byte_size if ready and artifact else None,
        sha256=artifact.sha256 if ready and artifact else None,
        generated_at=artifact.created_at if ready and artifact else None,
        expires_at=batch.retention_until if task else None,
        last_error_code=task.last_error_code if task else None,
        downloadable=ready and can_download,
    )


def batch_view(
    batch: ImportBatch,
    tasks: list[ImportTask],
    source: ImportArtifact | None,
    *,
    now: datetime,
    type_name: str,
    creator_name: str,
    next_actions: list[str],
    retryable_count: int,
    excluded_count: int,
    business_preview: dict[str, Any] | None = None,
) -> dict[str, Any]:
    precheck = next((t for t in tasks if t.phase == "precheck"), None)
    preview = None
    if batch.preview_version and batch.status != "prechecking" and not unpublished_input(tasks):
        preview = dict(
            version=batch.preview_version,
            fingerprint=batch.preview_fingerprint,
            generated_at=precheck.completed_at
            if precheck and precheck.completed_at
            else batch.updated_at,
            expires_at=batch.preview_expires_at,
        )
    return dict(
        id=batch.id,
        parent_batch_id=batch.parent_batch_id,
        import_type=batch.template_key,
        import_type_name=type_name,
        property_company_id=batch.property_company_id,
        template=dict(
            key=batch.template_key,
            version_no=batch.template_version_no,
            config_hash=batch.template_config_hash,
        ),
        scope=dict(
            type=batch.scope_type,
            id=batch.community_id or batch.property_company_id,
            name=batch.scope_snapshot.get("name", type_name),
        ),
        mode=batch.mode,
        status=batch.status,
        phase=phase(batch, tasks),
        last_error_code=batch.last_error_code,
        blocked_reason=("执行结果待核实" if batch.uncertain_rows else "任务已暂停，请核实后恢复")
        if batch.status == "blocked"
        else None,
        preview=preview,
        apply_policy=batch.apply_policy,
        include_warning_rows=batch.include_warning_rows,
        statistics=dict(
            total_rows=batch.total_rows,
            preview=dict(
                create_rows=batch.planned_create_rows,
                update_rows=0,
                skip_rows=batch.planned_skip_rows,
                warning_rows=batch.warning_rows,
                error_rows=batch.error_rows,
            ),
            execution=dict(
                created_rows=batch.created_rows,
                updated_rows=0,
                skipped_rows=batch.skipped_rows,
                failed_rows=batch.failed_rows,
                uncertain_rows=batch.uncertain_rows,
                cancelled_rows=batch.cancelled_rows,
                excluded_rows=excluded_count,
                processed_rows=batch.processed_rows,
                retryable_failed_rows=retryable_count,
            ),
        ),
        source_artifact=None
        if source is None
        else dict(
            id=source.id,
            file_name=source.original_filename if now < batch.retention_until else None,
            media_type=source.media_type,
            size_bytes=source.byte_size,
            sha256=source.sha256,
            expires_at=source.expires_at,
            available=now < batch.retention_until and source.deleted_at is None,
        ),
        active_task=task_view(active_task(tasks), progress=True),
        created_by=dict(id=batch.created_by_id, name=creator_name),
        created_at=batch.created_at,
        updated_at=batch.updated_at,
        retention_until=batch.retention_until,
        confirmed_at=batch.confirmed_at,
        started_at=batch.started_at,
        finished_at=batch.finished_at,
        next_actions=next_actions,
        business_preview=business_preview,
    )


def row_view(
    row: ImportRow,
    issues: list[ImportIssue],
    field_keys: frozenset[str],
    business_values: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = next((i for i in issues if i.phase == "apply"), None)
    code = result.code if result else None
    message = result.message if result else None
    if row.execution_status == "excluded":
        code = (
            "import.precheck_excluded"
            if row.validation_status == "invalid"
            else "import.policy_excluded"
        )
        message = (
            "预检未通过，未选择执行" if row.validation_status == "invalid" else "已按确认策略排除"
        )
    if row.execution_status == "cancelled":
        code = "import.cancelled"
        message = "已取消尚未提交的处理"
    return dict(
        id=row.id,
        row_no=row.source_row_no,
        precheck_status="pending"
        if row.validation_status == "staged"
        else "error"
        if row.validation_status == "invalid"
        else "warning"
        if row.warning_count
        else "valid",
        planned_action=row.planned_action,
        raw_values={k: v for k, v in (row.raw_values or {}).items() if k in field_keys},
        normalized_values=None
        if row.normalized_values is None
        else {k: v for k, v in row.normalized_values.items() if k in field_keys},
        issue_count=row.warning_count + row.error_count,
        execution_status=row.execution_status,
        result_code=code,
        result_message=message,
        result_at=row.result_at,
        business_values=business_values,
    )


def issue_view(
    issue: ImportIssue, row: ImportRow | None, field_keys: frozenset[str], retryable: bool
) -> dict[str, Any]:
    key = issue.field_key
    return dict(
        id=issue.id,
        preview_version=issue.preview_version,
        phase=issue.phase,
        row_no=row.source_row_no if row else None,
        column_index=issue.column_index,
        column_name=issue.column_name,
        field_key=key,
        cell_reference=issue.cell_reference,
        severity=issue.severity,
        code=issue.code,
        message=issue.message,
        suggestion=issue.suggestion,
        raw_value=(row.raw_values or {}).get(key) if row and key in field_keys else None,
        normalized_value=(row.normalized_values or {}).get(key)
        if row and key in field_keys
        else None,
        retryable=retryable,
    )
