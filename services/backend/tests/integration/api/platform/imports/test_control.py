from datetime import timedelta
from pathlib import Path

from pytest import MonkeyPatch
from sqlalchemy import func, select
from tests.support.admin import Harness, admin, company
from tests.support.imports.http import create_body, install_http_registry, publish_http_preview
from tests.support.workspace import create_community

from backend_app.models.imports import ImportArtifact, ImportBatch, ImportRequest, ImportTask


def test_create_upload_and_confirm_replay_first_safe_responses(
    harness: Harness,
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    install_http_registry(monkeypatch, tmp_path)
    target = company(harness)
    admin(harness, target["id"])
    enabled = harness.client.patch(
        f"/v1/property-companies/{target['id']}", json={"enabled": True}, headers=harness.headers()
    )
    assert enabled.status_code == 200
    body = create_body(target["id"], platform=True)
    headers = {**harness.headers(), "Idempotency-Key": "create-stable"}
    first = harness.client.post("/v1/import-batches", json=body, headers=headers)
    assert first.status_code == 201, first.text
    assert set(first.json()) == {
        "batch_id",
        "status",
        "phase",
        "preview_version",
        "active_task",
        "source_artifact",
    }
    assert first.headers["cache-control"] == "no-store"
    batch_id = first.json()["batch_id"]
    assert (
        harness.client.post("/v1/import-batches", json=body, headers=headers).json() == first.json()
    )
    community = create_community(harness, target["id"], "import-community")
    conflict = harness.client.post(
        "/v1/import-batches",
        json={**body, "scope": {"type": "community", "id": community["id"]}},
        headers=headers,
    )
    assert conflict.status_code == 409 and conflict.json()["code"] == "import.idempotency_conflict"
    path = f"/v1/import-batches/{batch_id}"
    upload_headers = {**harness.headers(), "Idempotency-Key": "upload-stable"}
    content = "编码,名称\nc2,first\nc3,second\n".encode()
    uploaded = harness.client.post(
        path + "/source-file",
        files={"file": ("input.csv", content, "text/csv")},
        headers=upload_headers,
    )
    assert uploaded.status_code == 202, uploaded.text
    replay = harness.client.post(
        path + "/source-file",
        files={"file": ("renamed.csv", content, "text/csv")},
        headers=upload_headers,
    )
    assert replay.status_code == 202 and replay.json() == uploaded.json()
    changed = harness.client.post(
        path + "/source-file",
        files={"file": ("input.csv", content.replace(b"first", b"changed"), "text/csv")},
        headers=upload_headers,
    )
    assert changed.status_code == 409 and changed.json()["code"] == "import.idempotency_conflict"
    assert harness.client.get(path + "/rows").status_code == 409
    publish_http_preview(harness.factory, batch_id)
    confirm_body = {
        "preview_version": 1,
        "preview_fingerprint": "b" * 64,
        "apply_policy": "all_rows",
        "include_warning_rows": True,
    }
    confirm_headers = {**harness.headers(), "Idempotency-Key": "confirm-stable"}
    confirmed = harness.client.post(path + "/confirm", json=confirm_body, headers=confirm_headers)
    assert confirmed.status_code == 202, confirmed.text
    assert confirmed.json()["status"] == "executing"
    replay = harness.client.post(path + "/confirm", json=confirm_body, headers=confirm_headers)
    assert replay.status_code == 202 and replay.json() == confirmed.json()
    changed = harness.client.post(
        path + "/confirm",
        json={**confirm_body, "include_warning_rows": False},
        headers=confirm_headers,
    )
    assert changed.status_code == 409 and changed.json()["code"] == "import.idempotency_conflict"
    with harness.factory() as db:
        assert db.scalar(select(func.count()).select_from(ImportBatch)) == 1
        assert db.scalar(select(func.count()).select_from(ImportArtifact)) == 1
        assert db.scalar(select(func.count()).select_from(ImportRequest)) == 3
        assert (
            db.scalar(
                select(func.count()).select_from(ImportTask).where(ImportTask.phase == "apply")
            )
            == 1
        )


def test_upload_replay_uses_first_response_after_source_expiry_without_recreating_files(
    harness: Harness,
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    _, storage = install_http_registry(monkeypatch, tmp_path)
    target = company(harness)
    admin(harness, target["id"])
    harness.client.patch(
        f"/v1/property-companies/{target['id']}", json={"enabled": True}, headers=harness.headers()
    )
    created = harness.client.post(
        "/v1/import-batches",
        json=create_body(target["id"], platform=True),
        headers={**harness.headers(), "Idempotency-Key": "create-expiry-replay"},
    )
    assert created.status_code == 201, created.text
    batch_id = created.json()["batch_id"]
    path = f"/v1/import-batches/{batch_id}/source-file"
    headers = {**harness.headers(), "Idempotency-Key": "upload-expiry-replay"}
    content = "编码,名称\nc1,record\n".encode()
    first = harness.client.post(
        path, files={"file": ("source.csv", content, "text/csv")}, headers=headers
    )
    assert first.status_code == 202, first.text
    with harness.factory() as db:
        batch = db.get(ImportBatch, batch_id)
        artifact = db.scalar(select(ImportArtifact).where(ImportArtifact.batch_id == batch_id))
        assert batch is not None and artifact is not None
        expired_at = batch.retention_until + timedelta(seconds=1)
        storage_key = artifact.storage_key
    storage.delete(storage_key)
    monkeypatch.setattr("backend_app.services.imports.control_plane.utc_now", lambda: expired_at)
    replay = harness.client.post(
        path, files={"file": ("source.csv", content, "text/csv")}, headers=headers
    )
    assert replay.status_code == 202 and replay.json() == first.json()
    assert not storage.path(storage_key).exists()
    new_request = harness.client.post(
        path,
        files={"file": ("source.csv", content, "text/csv")},
        headers={**headers, "Idempotency-Key": "new-after-expiry"},
    )
    assert new_request.status_code == 410 and new_request.json()["code"] == "import.data_expired"
    assert not storage.path(storage_key).exists()
