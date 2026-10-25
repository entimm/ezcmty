import pytest

from backend_app.core.errors import AppError
from backend_app.domain.admin.permissions import (
    normalize_permissions,
    permission_catalog,
    role_templates,
)
from backend_app.domain.admin.types import AdminScope


def test_business_dependencies_include_only_required_read_permissions() -> None:
    assert normalize_permissions("property_admin", ["property.bill.manage"]) == [
        "property.bill.manage",
        "property.bill.read",
    ]
    assert normalize_permissions("property_admin", ["property.bill_receipt.correct"]) == [
        "property.bill.read",
        "property.bill_receipt.correct",
    ]
    assert normalize_permissions("platform_admin", ["platform.payment.recover"]) == [
        "platform.payment.read",
        "platform.payment.recover",
        "platform.payment_reconciliation.read",
    ]


@pytest.mark.parametrize(
    "permission",
    ["property.system.manage", "platform.system.read", "property.house.create", "property.*"],
)
def test_role_input_rejects_system_foreign_unknown_and_wildcard_permissions(
    permission: str,
) -> None:
    with pytest.raises(AppError) as caught:
        normalize_permissions("property_admin", [permission])
    assert caught.value.code == "admin.invalid_permission"


@pytest.mark.parametrize("scope", ["platform_admin", "property_admin"])
def test_role_presets_are_complete_and_do_not_grant_key_operations(scope: AdminScope) -> None:
    selected = scope
    catalog = permission_catalog(selected)
    key_operations = {item.code for item in catalog if item.level in {"关键操作", "系统管理"}}
    templates = role_templates(selected)
    assert len(templates) == 3
    for template in templates:
        assert set(template.permissions).isdisjoint(key_operations)
        assert list(template.permissions) == normalize_permissions(selected, template.permissions)
    assert all(".import." not in item.code for item in catalog)
