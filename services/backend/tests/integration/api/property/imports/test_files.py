from pathlib import Path

import pytest
from pytest import MonkeyPatch
from sqlalchemy import select
from tests.support.housing import set_permissions
from tests.support.imports.http import (
    create_body,
    install_http_registry,
    publish_http_error_file,
    publish_http_preview,
)
from tests.support.workspace import PREFIX, WorkspaceHarness

from backend_app.models.imports import ImportBatch


def test_sensitive_rows_and_private_file_generation_are_projected_and_authorized(
    workspace: WorkspaceHarness,
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace.complete_login()
    _, storage = install_http_registry(
        monkeypatch,
        tmp_path,
        sensitive=True,
        required_permissions=("property.housing.manage",),
        read_permissions=("property.housing.read",),
    )
    created = workspace.client.post(
        f"{PREFIX}/import-batches",
        json=create_body(workspace.company_id),
        headers={**workspace.headers(), "Idempotency-Key": "file-batch"},
    )
    assert created.status_code == 201, created.text
    batch_id = created.json()["batch_id"]
    path = f"{PREFIX}/import-batches/{batch_id}"
    publish_http_preview(workspace.platform.factory, batch_id, invalid=True)
    rows = workspace.client.get(path + "/rows")
    assert rows.status_code == 200, rows.text
    assert "private-value" not in rows.text
    assert "name" not in rows.json()["items"][0]["raw_values"]
    issues = workspace.client.get(
        path + "/issues", params={"row_no": 3, "code": "import.invalid_format"}
    )
    assert issues.status_code == 200 and issues.json()["total"] == 1
    assert issues.json()["items"][0]["cell_reference"] == "B3"
    assert "private-value" not in issues.text
    missing = workspace.client.get(path + "/artifacts/error-file")
    assert missing.status_code == 200 and missing.json()["status"] == "not_generated"
    body = {"format": "csv", "preview_version": 1}
    headers = {**workspace.headers(), "Idempotency-Key": "file-generation"}
    scheduled = workspace.client.post(path + "/error-file", json=body, headers=headers)
    assert scheduled.status_code == 202, scheduled.text
    assert scheduled.json()["generation"] == 1
    early = workspace.client.get(path + "/artifacts/error-file/download", params={"generation": 1})
    assert early.status_code == 409 and early.json()["code"] == "import.error_file_not_ready"
    publish_http_error_file(workspace.platform.factory, batch_id, storage)
    ready = workspace.client.get(path + "/artifacts/error-file")
    assert ready.status_code == 200 and ready.json()["downloadable"] is True
    assert "storage_key" not in ready.text and str(tmp_path) not in ready.text
    downloaded = workspace.client.get(
        path + "/artifacts/error-file/download", params={"generation": 1}
    )
    assert downloaded.status_code == 200, downloaded.text
    assert downloaded.content == b"code,name\nC3,***\n"
    assert downloaded.headers["cache-control"] == "no-store"
    assert downloaded.headers["x-content-type-options"] == "nosniff"
    assert downloaded.headers["content-disposition"].startswith("attachment;")
    assert int(downloaded.headers["content-length"]) == len(downloaded.content)
    assert downloaded.headers["x-request-id"]
    assert (
        workspace.client.get(
            path + "/artifacts/error-file/download", params={"generation": 2}
        ).status_code
        == 409
    )
    assert workspace.client.get(path + "/artifacts/error-file/download").status_code == 422
    assert (
        workspace.client.get(
            path + "/artifacts/error-file/download", params={"generation": 0}
        ).status_code
        == 422
    )
    replay = workspace.client.post(path + "/error-file", json=body, headers=headers)
    assert replay.status_code == 202 and replay.json() == scheduled.json()
    with workspace.platform.factory() as db:
        batch = db.scalar(select(ImportBatch).where(ImportBatch.id == batch_id))
        assert batch
        batch.row_version += 1
        db.commit()
    stale = workspace.client.get(path + "/artifacts/error-file")
    assert stale.json()["status"] == "stale" and stale.json()["downloadable"] is False
    assert (
        workspace.client.get(
            path + "/artifacts/error-file/download", params={"generation": 1}
        ).status_code
        == 409
    )
    set_permissions(workspace, set())
    assert (
        workspace.client.get(
            path + "/artifacts/error-file/download", params={"generation": 1}
        ).status_code
        == 403
    )
    assert (
        workspace.client.post(
            path + "/error-file",
            json=body,
            headers={**workspace.headers(), "Idempotency-Key": "reader-generation"},
        ).status_code
        == 403
    )


def test_template_download_format_alias_and_file_response_headers(
    workspace: WorkspaceHarness,
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace.complete_login()
    install_http_registry(monkeypatch, tmp_path)
    root = f"{PREFIX}/import-types/test_records/versions/1"
    metadata = workspace.client.get(root)
    assert metadata.status_code == 200, metadata.text
    assert metadata.json()["version_no"] == 1
    assert len(metadata.json()["config_hash"]) == 64
    assert "sensitive" not in metadata.text
    xlsx = workspace.client.get(root + "/template-file")
    assert xlsx.status_code == 200, xlsx.text
    assert xlsx.content.startswith(b"PK")
    assert (
        xlsx.headers["content-type"]
        == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    csv = workspace.client.get(root + "/template-file", params={"format": "csv"})
    assert csv.status_code == 200, csv.text
    assert "编码,名称" in csv.content.decode("utf-8-sig")
    assert csv.headers["content-type"].startswith("text/csv")
    for response in (xlsx, csv):
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert "filename*=UTF-8''" in response.headers["content-disposition"]
        assert int(response.headers["content-length"]) == len(response.content)
    assert (
        workspace.client.get(root + "/template-file", params={"format": "pdf"}).status_code == 422
    )
    assert workspace.client.get(f"{PREFIX}/import-types/test_records/versions/0").status_code == 422


def test_oversized_multipart_envelope_is_rejected_before_file_spooling(
    workspace: WorkspaceHarness,
) -> None:
    workspace.complete_login()
    result = workspace.client.post(
        f"{PREFIX}/import-batches/00000000-0000-4000-8000-000000000001/source-file",
        files={"file": ("large.csv", b"x" * (10485760 + 65536), "text/csv")},
        headers={**workspace.headers(), "Idempotency-Key": "too-large-envelope"},
    )
    assert result.status_code == 413, result.text
    assert result.json()["code"] == "import.file_too_large"
    assert result.headers["cache-control"] == "no-store"


def test_schema_and_authorization_errors_are_never_cached(workspace: WorkspaceHarness) -> None:
    workspace.complete_login()
    schema = workspace.client.get(f"{PREFIX}/import-batches", params={"page_size": 101})
    assert schema.status_code == 422, schema.text
    assert schema.headers["cache-control"] == "no-store"
    missing_body = workspace.client.post(
        f"{PREFIX}/import-batches",
        json={},
        headers={**workspace.headers(), "Idempotency-Key": "invalid-body"},
    )
    assert missing_body.status_code == 422, missing_body.text
    assert missing_body.headers["cache-control"] == "no-store"
    set_permissions(workspace, set())
    forbidden = workspace.client.post(
        f"{PREFIX}/import-batches",
        json={
            "import_type": "houses",
            "template_version_no": 1,
            "scope": {"type": "community", "id": workspace.community_id},
            "mode": "create",
        },
        headers={**workspace.headers(), "Idempotency-Key": "forbidden-target-type"},
    )
    assert forbidden.status_code == 403, forbidden.text
    assert forbidden.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("duplicate", [False, True], ids=["unknown-field", "duplicate-file"])
def test_source_multipart_accepts_exactly_one_file_field(
    workspace: WorkspaceHarness,
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
    duplicate: bool,
) -> None:
    workspace.complete_login()
    install_http_registry(monkeypatch, tmp_path)
    created = workspace.client.post(
        f"{PREFIX}/import-batches",
        json=create_body(workspace.company_id),
        headers={**workspace.headers(), "Idempotency-Key": "strict-upload-draft"},
    )
    assert created.status_code == 201, created.text
    path = f"{PREFIX}/import-batches/{created.json()['batch_id']}/source-file"
    content = "编码,名称\na,测试\n".encode()
    files = [("file", ("first.csv", content, "text/csv"))]
    if duplicate:
        files.append(("file", ("second.csv", content, "text/csv")))
    result = workspace.client.post(
        path,
        files=files,
        data={} if duplicate else {"scope_id": "cannot-replace-scope"},
        headers={**workspace.headers(), "Idempotency-Key": "strict-upload"},
    )
    assert result.status_code == 422, result.text
    assert result.headers["cache-control"] == "no-store"
