from datetime import timedelta
from pathlib import Path

from pytest import MonkeyPatch
from sqlalchemy import select
from tests.support.imports.http import create_body, install_http_registry, publish_http_preview
from tests.support.workspace import PREFIX, WorkspaceHarness

from backend_app.models.admin import utc_now
from backend_app.models.imports import ImportBatch, ImportOperation, ImportRow, ImportTask


def test_paused_unpublished_recheck_hides_preview_rows_and_requires_original_recovery(
    workspace: WorkspaceHarness,
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    install_http_registry(monkeypatch, tmp_path)
    created = workspace.client.post(
        f"{PREFIX}/import-batches",
        json=create_body(workspace.company_id),
        headers={**workspace.headers(), "Idempotency-Key": "paused-recheck"},
    )
    assert created.status_code == 201, created.text
    batch_id = created.json()["batch_id"]
    path = f"{PREFIX}/import-batches/{batch_id}"
    publish_http_preview(workspace.platform.factory, batch_id)
    with workspace.platform.factory() as db:
        batch = db.get(ImportBatch, batch_id)
        task = db.scalar(
            select(ImportTask).where(
                ImportTask.batch_id == batch_id, ImportTask.phase == "precheck"
            )
        )
        assert batch and task
        batch.status = "blocked"
        batch.last_error_code = "import.task_paused"
        task.status = "paused"
        task.completed_at = None
        task.last_error_code = "import.task_paused"
        task.checkpoint = {"schema_version": 1, "target_preview_version": 2, "next_row_no": 3}
        db.commit()
    detail = workspace.client.get(path)
    assert detail.status_code == 200, detail.text
    assert detail.json()["status"] == "blocked" and detail.json()["preview"] is None
    for suffix in ("/rows", "/issues"):
        hidden = workspace.client.get(path + suffix)
        assert hidden.status_code == 409, hidden.text
        assert "private-value" not in hidden.text
    denied = workspace.client.post(
        path + "/precheck",
        json={"preview_version": 1},
        headers={**workspace.headers(), "Idempotency-Key": "replace-paused-task"},
    )
    assert denied.status_code == 409, denied.text
    premature_file = workspace.client.post(
        path + "/error-file",
        json={"format": "csv", "preview_version": 1},
        headers={**workspace.headers(), "Idempotency-Key": "file-from-unpublished-preview"},
    )
    assert premature_file.status_code == 409, premature_file.text
    recovered = workspace.client.post(
        path + "/recover",
        json={"reason": "原任务阻断已核实，继续原预检代次"},
        headers={**workspace.headers(), "Idempotency-Key": "resume-original-recheck"},
    )
    assert recovered.status_code == 202, recovered.text
    assert recovered.json()["status"] == "prechecking"
    assert workspace.client.get(path).json()["preview"] is None
    with workspace.platform.factory() as db:
        batch = db.get(ImportBatch, batch_id)
        task = db.scalar(
            select(ImportTask).where(
                ImportTask.batch_id == batch_id, ImportTask.phase == "precheck"
            )
        )
        assert batch and task and batch.confirmed_at is None
        assert task.status == "ready" and task.checkpoint["target_preview_version"] == 2


def test_running_artifact_does_not_block_safe_cancellation_or_keep_old_file_current(
    workspace: WorkspaceHarness,
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    install_http_registry(monkeypatch, tmp_path)
    created = workspace.client.post(
        f"{PREFIX}/import-batches",
        json=create_body(workspace.company_id),
        headers={**workspace.headers(), "Idempotency-Key": "cancel-artifact-batch"},
    )
    assert created.status_code == 201, created.text
    batch_id = created.json()["batch_id"]
    path = f"{PREFIX}/import-batches/{batch_id}"
    publish_http_preview(workspace.platform.factory, batch_id, invalid=True)
    artifact = workspace.client.post(
        path + "/error-file",
        json={"format": "csv", "preview_version": 1},
        headers={**workspace.headers(), "Idempotency-Key": "prepare-running-artifact"},
    )
    assert artifact.status_code == 202, artifact.text
    with workspace.platform.factory() as db:
        task = db.scalar(
            select(ImportTask).where(
                ImportTask.batch_id == batch_id, ImportTask.phase == "artifact"
            )
        )
        assert task
        task.status = "running"
        task.attempt_count = 1
        task.lease_expires_at = utc_now() + timedelta(seconds=60)
        db.commit()
    cancelled = workspace.client.post(
        path + "/cancel",
        headers={**workspace.headers(), "Idempotency-Key": "cancel-with-artifact"},
    )
    assert cancelled.status_code == 202, cancelled.text
    assert cancelled.json()["status"] == "cancelled"
    detail = workspace.client.get(path)
    assert detail.json()["status"] == "cancelled" and detail.json()["finished_at"]
    file = workspace.client.get(path + "/artifacts/error-file")
    assert file.json()["status"] == "stale" and file.json()["downloadable"] is False
    assert (
        workspace.client.get(
            path + "/artifacts/error-file/download", params={"generation": 1}
        ).status_code
        == 409
    )
    with workspace.platform.factory() as db:
        rows = db.scalars(select(ImportRow).where(ImportRow.batch_id == batch_id)).all()
        assert rows and all(row.execution_status == "cancelled" for row in rows)
        operations = db.scalars(select(ImportOperation)).all()
        assert operations and all(operation.status == "ready" for operation in operations)
