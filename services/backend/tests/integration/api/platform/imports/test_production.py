from tests.support.admin import Harness, company


def test_production_catalogue_is_empty_and_unregistered_types_are_rejected(
    harness: Harness,
) -> None:
    harness.login()
    target = company(harness)
    catalogue = harness.client.get("/v1/import-types")
    assert catalogue.status_code == 200, catalogue.text
    assert catalogue.json() == {"items": []}
    assert catalogue.headers["cache-control"] == "no-store"
    result = harness.client.post(
        "/v1/import-batches",
        json={
            "import_type": "unregistered_type",
            "template_version_no": 1,
            "property_company_id": target["id"],
            "scope": {"type": "company", "id": target["id"]},
            "mode": "create",
        },
        headers={**harness.headers(), "Idempotency-Key": "unregistered"},
    )
    assert result.status_code == 409, result.text
    assert result.json()["code"] == "import.template_unavailable"
    assert "storage" not in result.text and "Traceback" not in result.text


def test_import_writes_require_current_origin_csrf_and_idempotency_key(harness: Harness) -> None:
    harness.login()
    body = {
        "import_type": "unregistered_type",
        "template_version_no": 1,
        "scope": {"type": "company", "id": "00000000-0000-4000-8000-000000000001"},
        "property_company_id": "00000000-0000-4000-8000-000000000001",
        "mode": "create",
    }
    missing_csrf = harness.client.post(
        "/v1/import-batches", json=body, headers={"Idempotency-Key": "missing-csrf"}
    )
    assert missing_csrf.status_code == 403, missing_csrf.text
    foreign = harness.client.post(
        "/v1/import-batches",
        json=body,
        headers={
            **harness.headers(),
            "Origin": "https://foreign.invalid",
            "Idempotency-Key": "bad-origin",
        },
    )
    assert foreign.status_code == 403, foreign.text
    missing_key = harness.client.post("/v1/import-batches", json=body, headers=harness.headers())
    assert missing_key.status_code == 422, missing_key.text
    assert harness.client.get("/v1/import-batches", params={"page_size": 101}).status_code == 422
