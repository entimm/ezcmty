from dataclasses import asdict, replace
from typing import Any

import pytest

from backend_app.domain.imports.fingerprints import fingerprint
from backend_app.domain.imports.registry import ImportDefinition, ImportField
from backend_app.import_definitions.catalog import JsonImportRegistry, get_import_registry


class Adapter:
    def normalize(self) -> None:
        pass

    def prepare(self) -> None:
        pass

    def required_permissions(self) -> None:
        pass

    def plan(self) -> None:
        pass

    def execute(self) -> None:
        pass

    def revalidate(self) -> None:
        pass

    def resolve_operation(self) -> None:
        pass


def _definition() -> ImportDefinition:
    return ImportDefinition(
        "fixture",
        "测试",
        1,
        "fixture_v1",
        (ImportField("name", "名称", 1),),
        released_at="2026-10-23T00:00:00Z",
    )


def test_registry_preserves_immutable_version_identity_and_rejects_drift() -> None:
    first = _definition()
    retained = replace(first, version_no=2, available_for_new_batches=False)
    registry = JsonImportRegistry((first, retained), {"fixture_v1": Adapter()})
    assert len(first.config_hash) == 64
    assert registry.get("fixture", 1, first.config_hash) == first
    assert registry.get("fixture", 2) == retained
    with pytest.raises(ValueError, match="import.template_drift"):
        registry.get("fixture", 1, "0" * 64)
    with pytest.raises(ValueError, match="import.template_unavailable"):
        registry.get("fixture", 3)
    assert all(definition.key != "test_records" for definition in get_import_registry().list())


def test_registry_rejects_duplicate_versions_and_missing_adapter() -> None:
    definition = _definition()
    with pytest.raises(ValueError, match="Missing import adapter"):
        JsonImportRegistry((definition,))
    with pytest.raises(ValueError, match="Duplicate import definition"):
        JsonImportRegistry((definition, definition), {"fixture_v1": Adapter()})


def test_legacy_definition_digest_ignores_new_empty_read_permissions() -> None:
    definition = _definition()
    legacy = asdict(definition)
    legacy.pop("read_permissions")
    assert definition.config_hash == fingerprint(legacy)
    assert (
        replace(definition, read_permissions=("property.bill.read",)).config_hash
        != definition.config_hash
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"version_no": 0},
        {"version_no": True},
        {"key": "Invalid"},
        {"fields": (ImportField("name", "名称", 1), ImportField("name", "名称2", 2))},
        {"supported_modes": ("update",)},
        {"allowed_scope_types": ("resource_set",)},
        {"fields": (ImportField("name", "名称", 1, normalization_rules=("eval",)),)},
    ],
)
def test_configuration_validation_rejects_invalid_release(changes: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        replace(_definition(), **changes)
