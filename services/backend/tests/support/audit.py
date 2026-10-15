from __future__ import annotations

from typing import Any

from backend_app.models.admin import AdminAccount
from tests.support.admin import Harness, admin, company


def provision_company(h: Harness, name: str) -> tuple[str, str]:
    company_data = company(h, name)
    account_data = admin(h, company_data["id"], name)
    response = h.client.patch(
        f"/v1/property-companies/{company_data['id']}",
        json={"enabled": True},
        headers=h.headers(),
    )
    assert response.status_code == 200
    with h.factory() as db:
        account = db.get(AdminAccount, account_data["id"])
        assert account
        account.must_change_password = False
        db.commit()
    return str(company_data["id"]), str(account_data["id"])


def audit_filters(**overrides: Any) -> dict[str, Any]:
    return {
        "page": 1,
        "page_size": 20,
        "from_time": None,
        "to_time": None,
        "action": None,
        "result": None,
        "request_id": None,
        "sort": "-created_at",
        **overrides,
    }
