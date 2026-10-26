from tests.support.housing import set_permissions
from tests.support.workspace import PREFIX, WorkspaceHarness


def test_property_production_catalogue_does_not_expose_test_types(
    workspace: WorkspaceHarness,
) -> None:
    result = workspace.client.get(f"{PREFIX}/import-types")
    assert result.status_code == 200, result.text
    assert all(item["key"] != "test_records" for item in result.json()["items"])
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


def test_empty_role_lists_empty_types_but_cannot_create_or_read_target_batches(
    workspace: WorkspaceHarness,
) -> None:
    body = {
        "import_type": "houses",
        "template_version_no": 1,
        "scope": {"type": "community", "id": workspace.community_id},
        "mode": "create",
    }
    created = workspace.client.post(
        f"{PREFIX}/import-batches",
        json=body,
        headers={**workspace.headers(), "Idempotency-Key": "before-revocation"},
    )
    assert created.status_code == 201, created.text
    batch_id = created.json()["batch_id"]
    set_permissions(workspace, set())
    listing = workspace.client.get(f"{PREFIX}/import-batches")
    assert listing.status_code == 200, listing.text
    assert listing.json()["total"] == 0
    catalogue = workspace.client.get(f"{PREFIX}/import-types")
    assert catalogue.status_code == 200 and catalogue.json() == {"items": []}
    rejected = workspace.client.post(
        f"{PREFIX}/import-batches",
        json=body,
        headers={**workspace.headers(), "Idempotency-Key": "reader-create"},
    )
    assert rejected.status_code == 403, rejected.text
    download = workspace.client.get(
        f"{PREFIX}/import-batches/{batch_id}/artifacts/error-file/download",
        params={"generation": 1},
    )
    assert download.status_code == 403, download.text
