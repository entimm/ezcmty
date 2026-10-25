from pathlib import Path

from pytest import MonkeyPatch
from tests.support.housing import set_permissions
from tests.support.imports.adapter import TestRecordAdapter
from tests.support.imports.http import create_body, install_http_registry, publish_http_preview
from tests.support.imports.pipeline import drain_worker
from tests.support.workspace import PREFIX, WorkspaceHarness

from backend_app.core.config import get_settings
from backend_app.import_definitions.catalog import JsonImportRegistry
from backend_app.services.worker.imports.pipeline import ImportWorkerService


def test_import_history_is_filtered_by_target_business_before_pagination(
    workspace: WorkspaceHarness,
) -> None:
    workspace.complete_login()
    batches = {}
    for import_type in ("houses", "property_fee_bills"):
        result = workspace.client.post(
            f"{PREFIX}/import-batches",
            json={
                "import_type": import_type,
                "template_version_no": 1,
                "scope": {"type": "community", "id": workspace.community_id},
                "mode": "create",
            },
            headers={**workspace.headers(), "Idempotency-Key": import_type},
        )
        assert result.status_code == 201, result.text
        batches[import_type] = result.json()["batch_id"]
    set_permissions(workspace, {"property.housing.read"})
    listing = workspace.client.get(f"{PREFIX}/import-batches")
    assert listing.status_code == 200, listing.text
    assert listing.json()["total"] == 1
    assert [item["import_type"] for item in listing.json()["items"]] == ["houses"]
    page = workspace.client.get(f"{PREFIX}/import-batches", params={"page": 99, "page_size": 1})
    assert page.json()["total"] == 1 and page.json()["items"] == []
    detail = workspace.client.get(f"{PREFIX}/import-batches/{batches['houses']}")
    assert detail.status_code == 200 and detail.json()["template_fields"]
    assert (
        workspace.client.get(f"{PREFIX}/import-batches/{batches['property_fee_bills']}").status_code
        == 403
    )
    assert workspace.client.get(f"{PREFIX}/import-types").json() == {"items": []}


def test_target_business_reader_can_generate_and_download_error_file_without_processing(
    workspace: WorkspaceHarness, monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    workspace.complete_login()
    definition, storage = install_http_registry(
        monkeypatch,
        tmp_path,
        sensitive=True,
        required_permissions=("property.housing.manage",),
        read_permissions=("property.housing.read",),
    )
    result = workspace.client.post(
        f"{PREFIX}/import-batches",
        json=create_body(workspace.company_id),
        headers={**workspace.headers(), "Idempotency-Key": "business-reader-batch"},
    )
    assert result.status_code == 201, result.text
    batch_id = result.json()["batch_id"]
    path = f"{PREFIX}/import-batches/{batch_id}"
    publish_http_preview(workspace.platform.factory, batch_id, invalid=True)
    set_permissions(workspace, {"property.housing.read"})
    detail = workspace.client.get(path).json()
    assert "generate_error_file" in detail["next_actions"]
    assert "confirm" not in detail["next_actions"] and "cancel" not in detail["next_actions"]
    generated = workspace.client.post(
        path + "/error-file",
        json={"format": "csv", "preview_version": 1},
        headers={**workspace.headers(), "Idempotency-Key": "business-reader-error-file"},
    )
    assert generated.status_code == 202, generated.text
    worker = ImportWorkerService(
        workspace.platform.factory,
        get_settings(),
        registry=JsonImportRegistry((definition,), {"test_records": TestRecordAdapter()}),
        storage=storage,
    )
    drain_worker(workspace.platform.factory, worker)
    downloaded = workspace.client.get(
        path + "/artifacts/error-file/download",
        params={"generation": generated.json()["generation"]},
    )
    assert downloaded.status_code == 200, downloaded.text
    assert "private-value" not in downloaded.text
    denied = workspace.client.post(
        path + "/cancel", headers={**workspace.headers(), "Idempotency-Key": "reader-cancel"}
    )
    assert denied.status_code == 403
