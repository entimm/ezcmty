from pathlib import Path

from pytest import MonkeyPatch
from sqlalchemy import text
from tests.support.imports.adapter import TestRecordAdapter, install_test_records
from tests.support.imports.http import create_body, install_http_registry
from tests.support.imports.pipeline import drain_worker
from tests.support.workspace import PREFIX, WorkspaceHarness

from backend_app.core.config import get_settings
from backend_app.import_definitions.catalog import JsonImportRegistry
from backend_app.services.worker.imports.pipeline import ImportWorkerService


def test_http_upload_worker_preview_partial_execution_retry_and_original_history(
    workspace: WorkspaceHarness,
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    adapter = TestRecordAdapter()
    definition, storage = install_http_registry(monkeypatch, tmp_path, adapter=adapter)
    registry = JsonImportRegistry((definition,), {"test_records": adapter})
    worker = ImportWorkerService(workspace.platform.factory, get_settings(), registry, storage)
    with workspace.platform.factory() as db:
        install_test_records(db)
        db.commit()
    created = workspace.client.post(
        f"{PREFIX}/import-batches",
        json=create_body(workspace.company_id),
        headers={**workspace.headers(), "Idempotency-Key": "whole-flow-create"},
    )
    assert created.status_code == 201, created.text
    source_id = created.json()["batch_id"]
    source_path = f"{PREFIX}/import-batches/{source_id}"
    uploaded = workspace.client.post(
        source_path + "/source-file",
        files={"file": ("records.csv", "编码,名称\na,正常\nb,RETRY\n".encode(), "text/csv")},
        headers={**workspace.headers(), "Idempotency-Key": "whole-flow-upload"},
    )
    assert uploaded.status_code == 202, uploaded.text
    assert drain_worker(workspace.platform.factory, worker) >= 2
    preview = workspace.client.get(source_path).json()
    assert preview["status"] == "preview_ready", preview
    assert preview["statistics"]["preview"]["create_rows"] == 2
    with workspace.platform.factory() as db:
        assert db.scalar(text("SELECT count(*) FROM import_test_records")) == 0
    confirm = workspace.client.post(
        source_path + "/confirm",
        json={
            "preview_version": preview["preview"]["version"],
            "preview_fingerprint": preview["preview"]["fingerprint"],
            "apply_policy": "all_rows",
            "include_warning_rows": False,
        },
        headers={**workspace.headers(), "Idempotency-Key": "whole-flow-confirm"},
    )
    assert confirm.status_code == 202, confirm.text
    drain_worker(workspace.platform.factory, worker)
    original = workspace.client.get(source_path).json()
    original_rows = workspace.client.get(source_path + "/rows").json()["items"]
    assert original["status"] == "partial_failed", original
    assert original["statistics"]["execution"]["created_rows"] == 1
    assert original["statistics"]["execution"]["failed_rows"] == 1
    assert original["statistics"]["execution"]["retryable_failed_rows"] == 1
    artifact = workspace.client.post(
        source_path + "/error-file",
        json={"format": "csv", "preview_version": 1},
        headers={**workspace.headers(), "Idempotency-Key": "whole-flow-file"},
    )
    assert artifact.status_code == 202, artifact.text
    drain_worker(workspace.platform.factory, worker)
    state = workspace.client.get(source_path + "/artifacts/error-file").json()
    assert state["status"] == "ready" and state["downloadable"], str(state)
    downloaded = workspace.client.get(
        source_path + "/artifacts/error-file/download",
        params={"generation": state["generation"]},
    )
    assert downloaded.status_code == 200, downloaded.text
    assert "import.system_error" in downloaded.content.decode("utf-8-sig")
    assert "failed" in downloaded.content.decode("utf-8-sig")
    retried = workspace.client.post(
        source_path + "/retry-failed",
        json={"selection": "retryable_only"},
        headers={**workspace.headers(), "Idempotency-Key": "whole-flow-retry"},
    )
    assert retried.status_code == 201, retried.text
    assert retried.json()["selected_rows"] == 1
    retry_id = retried.json()["batch"]["batch_id"]
    retry_path = f"{PREFIX}/import-batches/{retry_id}"
    adapter.allow_retry = True
    drain_worker(workspace.platform.factory, worker)
    retry = workspace.client.get(retry_path).json()
    assert retry["status"] == "preview_ready", retry
    assert retry["parent_batch_id"] == source_id
    assert retry["confirmed_at"] is None and retry["apply_policy"] is None
    assert retry["retention_until"] == original["retention_until"]
    with workspace.platform.factory() as db:
        assert db.scalar(text("SELECT count(*) FROM import_test_records")) == 1
    second_confirmation = workspace.client.post(
        retry_path + "/confirm",
        json={
            "preview_version": retry["preview"]["version"],
            "preview_fingerprint": retry["preview"]["fingerprint"],
            "apply_policy": "all_rows",
            "include_warning_rows": False,
        },
        headers={**workspace.headers(), "Idempotency-Key": "whole-flow-retry-confirm"},
    )
    assert second_confirmation.status_code == 202, second_confirmation.text
    drain_worker(workspace.platform.factory, worker)
    result = workspace.client.get(retry_path).json()
    assert result["status"] == "completed", result
    assert result["statistics"]["execution"]["created_rows"] == 1
    after = workspace.client.get(source_path).json()
    assert after["status"] == "partial_failed"
    for key in ("created_rows", "failed_rows", "processed_rows"):
        assert after["statistics"]["execution"][key] == original["statistics"]["execution"][key]
    assert workspace.client.get(source_path + "/rows").json()["items"] == original_rows
    with workspace.platform.factory() as db:
        assert db.scalar(text("SELECT count(*) FROM import_test_records")) == 2
