from __future__ import annotations


def test_property_runtime_exposes_no_onboarding_routes() -> None:
    from backend_app.app_factory import create_app

    paths = create_app("property-admin-api").openapi()["paths"]
    assert "/v1/property-companies" not in paths
    assert "/v1/admin-sessions" in paths and "/v1/property-companies/current" in paths
    assert "/v1/property-workspace/summary" in paths
    assert "/v1/admin-accounts" not in paths and "/v1/admin-audit-logs" not in paths
    assert set(paths["/v1/communities"]) == {"get"}
    assert set(paths["/v1/communities/{community_id}"]) == {"get"}
