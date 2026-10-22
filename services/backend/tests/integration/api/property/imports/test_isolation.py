from pathlib import Path

from pytest import MonkeyPatch
from tests.support.admin import company
from tests.support.housing import set_permissions
from tests.support.imports.http import create_body, install_http_registry, publish_http_preview
from tests.support.workspace import PREFIX, WorkspaceHarness


def test_backend_company_scope_and_pagination_are_applied_before_visibility(
    workspace: WorkspaceHarness,
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace.complete_login()
    install_http_registry(monkeypatch, tmp_path)
    headers = {**workspace.headers(), "Idempotency-Key": "own-property"}
    body = create_body(workspace.company_id)
    created = workspace.client.post(f"{PREFIX}/import-batches", json=body, headers=headers)
    assert created.status_code == 201, created.text
    own = created.json()["batch_id"]
    assert workspace.platform.client.get(f"/v1/import-batches/{own}").status_code == 404
    platform_body = create_body(workspace.company_id, platform=True)
    platform_created = workspace.platform.client.post(
        "/v1/import-batches",
        json=platform_body,
        headers={**workspace.platform.headers(), "Idempotency-Key": "platform-own"},
    )
    assert platform_created.status_code == 201, platform_created.text
    foreign = platform_created.json()["batch_id"]
    for suffix in ("", "/rows", "/issues", "/events", "/artifacts/error-file"):
        assert workspace.client.get(f"{PREFIX}/import-batches/{foreign}{suffix}").status_code == 404
    other = company(workspace.platform, "other-import-company")
    rejected = workspace.client.post(
        f"{PREFIX}/import-batches",
        json={**body, "property_company_id": other["id"]},
        headers={**headers, "Idempotency-Key": "inject-company"},
    )
    assert rejected.status_code == 422, rejected.text
    swapped = workspace.client.post(
        f"{PREFIX}/import-batches",
        json=create_body(other["id"]),
        headers={**headers, "Idempotency-Key": "swap-scope"},
    )
    assert swapped.status_code == 422, swapped.text
    listing = workspace.client.get(f"{PREFIX}/import-batches", params={"page": 99, "page_size": 1})
    assert (
        listing.status_code == 200
        and listing.json()["total"] == 1
        and listing.json()["items"] == []
    )
    assert (
        workspace.client.get(
            f"{PREFIX}/import-batches", params={"property_company_id": workspace.company_id}
        ).status_code
        == 422
    )
    publish_http_preview(workspace.platform.factory, own)
    rows = workspace.client.get(
        f"{PREFIX}/import-batches/{own}/rows", params={"page": 3, "page_size": 1}
    )
    assert rows.status_code == 200 and rows.json()["total"] == 2 and rows.json()["items"] == []
    first = workspace.client.get(f"{PREFIX}/import-batches/{own}/rows", params={"page_size": 1})
    assert [row["row_no"] for row in first.json()["items"]] == [2]


def test_generic_create_permission_does_not_grant_adapter_business_permission(
    workspace: WorkspaceHarness,
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace.complete_login()
    install_http_registry(monkeypatch, tmp_path, required_permissions=("property.community.read",))
    set_permissions(workspace, {"property.import.create", "property.import.read"})
    catalogue = workspace.client.get(f"{PREFIX}/import-types")
    assert catalogue.status_code == 200 and catalogue.json() == {"items": []}
    rejected = workspace.client.post(
        f"{PREFIX}/import-batches",
        json=create_body(workspace.company_id),
        headers={**workspace.headers(), "Idempotency-Key": "no-business-permission"},
    )
    assert rejected.status_code == 403, rejected.text


def test_confirmation_rejects_missing_policy_stale_preview_and_implicit_error_skips(
    workspace: WorkspaceHarness,
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace.complete_login()
    install_http_registry(monkeypatch, tmp_path)
    created = workspace.client.post(
        f"{PREFIX}/import-batches",
        json=create_body(workspace.company_id),
        headers={**workspace.headers(), "Idempotency-Key": "confirmation-guards"},
    )
    assert created.status_code == 201, created.text
    batch_id = created.json()["batch_id"]
    publish_http_preview(workspace.platform.factory, batch_id, invalid=True)
    path = f"{PREFIX}/import-batches/{batch_id}/confirm"
    body = {
        "preview_version": 1,
        "preview_fingerprint": "b" * 64,
        "apply_policy": "all_rows",
        "include_warning_rows": False,
    }
    headers = {**workspace.headers(), "Idempotency-Key": "confirmed-policy"}
    missing = {key: value for key, value in body.items() if key != "include_warning_rows"}
    assert workspace.client.post(path, json=missing, headers=headers).status_code == 422
    stale = workspace.client.post(path, json={**body, "preview_version": 2}, headers=headers)
    assert stale.status_code == 409 and stale.json()["code"] == "import.preview_stale"
    implicit_skip = workspace.client.post(path, json=body, headers=headers)
    assert implicit_skip.status_code == 409
    selected = workspace.client.post(
        path, json={**body, "apply_policy": "valid_rows_only"}, headers=headers
    )
    assert selected.status_code == 202, selected.text
    detail = workspace.client.get(f"{PREFIX}/import-batches/{batch_id}")
    assert detail.json()["apply_policy"] == "valid_rows_only"
    assert detail.json()["include_warning_rows"] is False
    assert detail.json()["statistics"]["execution"]["excluded_rows"] == 1
