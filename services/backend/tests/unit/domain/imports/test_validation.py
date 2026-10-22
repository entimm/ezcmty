from typing import Any

import pytest

from backend_app.domain.imports.registry import ImportDefinition, ImportField
from backend_app.domain.imports.validation import normalize_fields, validate_fields


@pytest.mark.parametrize(
    "field,value",
    [
        (ImportField("value", "字段", 1, required=True), ""),
        (ImportField("value", "字段", 1, data_type="integer"), True),
        (ImportField("value", "字段", 1, data_type="integer"), "1.5"),
        (ImportField("value", "字段", 1, data_type="decimal"), "NaN"),
        (ImportField("value", "字段", 1, max_length=2), "三个字"),
        (ImportField("value", "字段", 1, enum_values=("one", "two")), "secret"),
        (ImportField("value", "字段", 1, format="email"), "private-invalid"),
        (ImportField("value", "字段", 1, data_type="date"), "2026-02-30"),
    ],
)
def test_declarative_field_issues_do_not_copy_input(field: ImportField, value: Any) -> None:
    definition = ImportDefinition("test", "测试", 1, "test", (field,))
    problems = validate_fields(definition, {"value": value})
    assert len(problems) == 1 and problems[0].code == "import.validation_failed"
    assert problems[0].field_key == "value" and problems[0].column_name == "字段"
    assert "secret" not in problems[0].message and "private-invalid" not in problems[0].message


def test_normalization_order_is_explicit_and_does_not_modify_original_values() -> None:
    field = ImportField("code", "编码", 1, normalization_rules=("trim", "uppercase"))
    definition = ImportDefinition("test", "测试", 1, "test", (field,))
    raw = {"code": " abc "}
    assert normalize_fields(definition, raw) == {"code": "ABC"}
    assert raw == {"code": " abc "}
    assert not validate_fields(definition, {"code": "ABC"})
