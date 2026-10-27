from copy import deepcopy
from dataclasses import FrozenInstanceError, asdict, replace
from typing import Any

import pytest

from backend_app.domain.imports.registry import (
    ImportDefinition,
    ImportField,
    definition_from_mapping,
)
from backend_app.import_definitions.catalog import get_import_registry


@pytest.mark.parametrize(
    "key,expected_hash",
    [
        (
            "house_owners",
            "77672e7506fae23849167fcfe8034deb2821799e1067a0b9a0979f390ee0a892",
        ),
        ("houses", "189fa14ea69205bf7e8f5719a853639819ef412d654bacf24fb6632f0dcd565b"),
        (
            "property_fee_bills",
            "36d871b6a44fedadcab916cf90b0efd61278577860b6769785287722d65c04a7",
        ),
    ],
)
def test_released_template_fingerprint_is_unchanged(key: str, expected_hash: str) -> None:
    assert get_import_registry().get(key, 1).config_hash == expected_hash


def test_definitions_preserve_positional_frozen_dataclass_operations() -> None:
    field = ImportField("name", "名称", 1, required=True)
    definition = ImportDefinition("fixture", "测试", 1, "fixture_v1", (field,))

    assert asdict(definition)["fields"] == (asdict(field),)
    assert definition.headers == ("名称",)
    assert replace(definition, version_no=2).version_no == 2
    assert replace(field, label="姓名").label == "姓名"
    assert definition.version_no == 1 and field.label == "名称"


@pytest.mark.parametrize(
    "value,attribute,replacement",
    [
        pytest.param(ImportField("name", "名称", 1), "label", "姓名", id="field"),
        pytest.param(
            ImportDefinition("fixture", "测试", 1, "fixture_v1", (ImportField("name", "名称", 1),)),
            "version_no",
            2,
            id="definition",
        ),
    ],
)
def test_configuration_dataclasses_remain_frozen(
    value: object, attribute: str, replacement: object
) -> None:
    with pytest.raises(FrozenInstanceError):
        setattr(value, attribute, replacement)


def _mapping() -> dict[str, Any]:
    return {
        "key": "fixture",
        "name": "测试",
        "version_no": 1,
        "adapter_key": "fixture_v1",
        "allowed_scope_types": ["community"],
        "fields": [{"key": "name", "label": "名称", "order": 1}],
    }


def test_json_definition_preserves_scalars_and_does_not_modify_source() -> None:
    raw = _mapping()
    raw["fields"][0].update(
        enum_values=["001", 1, 1.5, True, None],
        example="001",
        normalization_rules=["trim", "uppercase"],
    )
    original = deepcopy(raw)

    definition = definition_from_mapping(raw)

    assert raw == original
    assert definition.allowed_scope_types == ("community",)
    field = definition.fields[0]
    assert field.enum_values == ("001", 1, 1.5, True, None)
    assert tuple(type(value) for value in field.enum_values) == (str, int, float, bool, type(None))
    assert field.example == "001"
    assert field.normalization_rules == ("trim", "uppercase")


@pytest.mark.parametrize("location", ["definition", "field"])
def test_unknown_json_configuration_fields_are_rejected(location: str) -> None:
    raw = _mapping()
    target = raw if location == "definition" else raw["fields"][0]
    target["unexpected"] = "private-input"

    with pytest.raises(ValueError):
        definition_from_mapping(raw)


@pytest.mark.parametrize(
    "location,key,value",
    [
        pytest.param("definition", "version_no", True, id="boolean-is-not-version"),
        pytest.param("field", "order", True, id="boolean-is-not-column-order"),
        pytest.param("field", "max_length", True, id="boolean-is-not-length"),
        pytest.param("field", "required", 1, id="integer-is-not-required-flag"),
    ],
)
def test_json_configuration_rejects_scalar_coercion(location: str, key: str, value: Any) -> None:
    raw = _mapping()
    target = raw if location == "definition" else raw["fields"][0]
    target[key] = value

    with pytest.raises(ValueError):
        definition_from_mapping(raw)


@pytest.mark.parametrize(
    "fields",
    [
        pytest.param(
            (ImportField("name", "名称", 1), ImportField("name", "姓名", 2)),
            id="duplicate-key",
        ),
        pytest.param(
            (ImportField("name", "名称", 1), ImportField("other", "名称", 2)),
            id="duplicate-label",
        ),
        pytest.param(
            (ImportField("name", "名称", 1), ImportField("other", "其他", 1)),
            id="duplicate-order",
        ),
        pytest.param(
            (ImportField("second", "次列", 2), ImportField("first", "首列", 1)),
            id="unordered-columns",
        ),
        pytest.param((ImportField("name", "名称\n泄漏", 1),), id="control-character-in-label"),
        pytest.param(
            (ImportField("name", "名称", 1, enum_values=(float("nan"),)),),
            id="nan-enum-value",
        ),
        pytest.param(
            (ImportField("name", "名称", 1, enum_values=(float("inf"),)),),
            id="infinite-enum-value",
        ),
    ],
)
def test_definition_rejects_invalid_field_structure(fields: tuple[ImportField, ...]) -> None:
    with pytest.raises(ValueError):
        ImportDefinition("fixture", "测试", 1, "fixture_v1", fields)
