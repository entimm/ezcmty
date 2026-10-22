from tests.support.housing import set_permissions
from tests.support.workspace import PREFIX, WorkspaceHarness


def test_property_production_catalogue_does_not_expose_test_types(
    workspace: WorkspaceHarness,
) -> None:
    workspace.complete_login()
    result = workspace.client.get(f"{PREFIX}/import-types")
    assert result.status_code == 200, result.text
    assert result.json() == {"items": []}
    assert result.headers["cache-control"] == "no-store"
    rejected = workspace.client.post(
        f"{PREFIX}/import-batches",
        json={
            "import_type": "unregistered_type",
            "template_version_no": 1,
            "scope": {"type": "company", "id": workspace.company_id},
            "mode": "create",
        },
        headers={**workspace.headers(), "Idempotency-Key": "unknown-type"},
    )
    assert rejected.status_code == 409, rejected.text
    assert rejected.json()["code"] == "import.template_unavailable"


def test_read_permission_does_not_grant_type_creation_or_file_download(
    workspace: WorkspaceHarness,
) -> None:
    workspace.complete_login()
    set_permissions(workspace, {"property.import.read"})
    listing = workspace.client.get(f"{PREFIX}/import-batches")
    assert listing.status_code == 200, listing.text
    assert listing.json()["total"] == 0
    assert workspace.client.get(f"{PREFIX}/import-types").status_code == 403
    rejected = workspace.client.post(
        f"{PREFIX}/import-batches",
        json={
            "import_type": "unknown_type",
            "template_version_no": 1,
            "scope": {"type": "company", "id": workspace.company_id},
            "mode": "create",
        },
        headers={**workspace.headers(), "Idempotency-Key": "reader-create"},
    )
    assert rejected.status_code == 403, rejected.text
    download = workspace.client.get(
        f"{PREFIX}/import-batches/00000000-0000-4000-8000-000000000001/artifacts/error-file/download",
        params={"generation": 1},
    )
    assert download.status_code == 403, download.text
