from typing import Any

import pytest

from backend_app.domain.imports.registry import ImportDefinition, ImportField
from backend_app.domain.imports.types import ImportProblem
from backend_app.domain.imports.validation import normalize_fields, validate_fields


@pytest.mark.parametrize(
    "data_type,value,valid",
    [
        pytest.param("string", " 001 ", True, id="string-keeps-whitespace"),
        pytest.param("string", 12, False, id="string-rejects-number"),
        pytest.param("integer", 12, True, id="integer-number"),
        pytest.param("integer", "+0012", True, id="integer-signed-text"),
        pytest.param("integer", "١", True, id="integer-unicode-digit"),
        pytest.param("integer", "1\n", False, id="integer-rejects-trailing-newline"),
        pytest.param("integer", " 12 ", False, id="integer-rejects-whitespace"),
        pytest.param("integer", 12.0, False, id="integer-rejects-integral-float"),
        pytest.param("integer", True, False, id="integer-rejects-boolean"),
        pytest.param("decimal", " 1.20 ", True, id="decimal-whitespace-text"),
        pytest.param("decimal", "-1e-2", True, id="decimal-scientific-text"),
        pytest.param("decimal", 12, True, id="decimal-integer-number"),
        pytest.param("decimal", True, False, id="decimal-rejects-boolean"),
        pytest.param("decimal", "NaN", False, id="decimal-rejects-nan"),
        pytest.param("decimal", float("inf"), False, id="decimal-rejects-infinite-number"),
        pytest.param("boolean", False, True, id="boolean-false-is-not-empty"),
        pytest.param("boolean", "FALSE", True, id="boolean-case-insensitive-text"),
        pytest.param("boolean", 1, False, id="boolean-rejects-number"),
        pytest.param("boolean", "yes", False, id="boolean-rejects-other-truthy-text"),
        pytest.param("boolean", "falſe", False, id="boolean-rejects-long-s-casefold"),
        pytest.param("date", "20261023", True, id="date-compact-iso"),
        pytest.param("date", "2026-W44-2", True, id="date-iso-week"),
        pytest.param("date", "2026-02-30", False, id="date-rejects-invalid-day"),
        pytest.param("date", "2026-10-27T00:00:00", False, id="date-rejects-midnight-timestamp"),
        pytest.param("datetime", "2026-10-23", True, id="datetime-date-only-iso"),
        pytest.param("datetime", "2026-10-23T12:30:00+08:00", True, id="datetime-offset"),
        pytest.param("datetime", "not-a-date", False, id="datetime-rejects-invalid-text"),
        pytest.param("datetime", "1234567890", False, id="datetime-rejects-numeric-timestamp"),
    ],
)
def test_field_type_validation_preserves_imported_values(
    data_type: str, value: Any, valid: bool
) -> None:
    definition = ImportDefinition(
        "fixture", "测试", 1, "fixture", (ImportField("value", "字段", 1, data_type=data_type),)
    )
    values = {"value": value}

    problems = validate_fields(definition, values)

    assert values["value"] is value
    assert problems == (
        []
        if valid
        else [
            ImportProblem(
                "import.validation_failed",
                "字段类型不符合模板要求",
                field_key="value",
                column_name="字段",
                column_index=1,
            )
        ]
    )


@pytest.mark.parametrize(
    "format_name,value,valid",
    [
        pytest.param(
            "email", "alice\x1c@example.com", False, id="email-rejects-control-whitespace"
        ),
        pytest.param(
            "uuid",
            "{{00112233-4455-4677-8899-aabbccddeeff}}",
            True,
            id="uuid-brace-normalization",
        ),
        pytest.param("uuid", "not-a-uuid", False, id="uuid-rejects-invalid-text"),
    ],
)
def test_field_format_validation_preserves_existing_parser_boundaries(
    format_name: str, value: str, valid: bool
) -> None:
    definition = ImportDefinition(
        "fixture",
        "测试",
        1,
        "fixture",
        (ImportField("value", "字段", 1, format=format_name),),
    )

    problems = validate_fields(definition, {"value": value})

    assert [problem.message for problem in problems] == (
        [] if valid else ["字段格式不符合模板要求"]
    )


@pytest.mark.parametrize("value", [None, ""], ids=["null", "empty-text"])
@pytest.mark.parametrize("required", [False, True], ids=["optional", "required"])
def test_empty_value_only_applies_required_constraint(value: Any, required: bool) -> None:
    definition = ImportDefinition(
        "fixture",
        "测试",
        1,
        "fixture",
        (
            ImportField(
                "value",
                "字段",
                1,
                required=required,
                data_type="integer",
                max_length=1,
                enum_values=(1,),
                format="uuid",
            ),
        ),
    )

    problems = validate_fields(definition, {"value": value})

    assert [problem.message for problem in problems] == (["必填字段不能为空"] if required else [])


@pytest.mark.parametrize(
    "field,value,message",
    [
        pytest.param(
            ImportField(
                "value", "敏感字段", 3, data_type="integer", max_length=1, enum_values=(1,)
            ),
            "private-invalid",
            "字段类型不符合模板要求",
            id="type-before-length-and-enum",
        ),
        pytest.param(
            ImportField("value", "敏感字段", 3, max_length=2, enum_values=("ok",), format="email"),
            "private-invalid",
            "字段超过允许长度",
            id="length-before-enum-and-format",
        ),
        pytest.param(
            ImportField("value", "敏感字段", 3, enum_values=("ok",), format="email"),
            "private-invalid",
            "字段不在允许值范围内",
            id="enum-before-format",
        ),
    ],
)
def test_first_field_failure_keeps_safe_column_diagnostics(
    field: ImportField, value: str, message: str
) -> None:
    definition = ImportDefinition("fixture", "测试", 1, "fixture", (field,))

    assert validate_fields(definition, {"value": value}) == [
        ImportProblem(
            "import.validation_failed",
            message,
            field_key="value",
            column_name="敏感字段",
            column_index=3,
        )
    ]


@pytest.mark.parametrize(
    "data_type,value,allowed,valid",
    [
        pytest.param("integer", "001", "001", True, id="integer-text-enum"),
        pytest.param("integer", 1, "001", False, id="integer-enum-does-not-coerce"),
        pytest.param("decimal", "1.00", "1.00", True, id="decimal-text-enum"),
        pytest.param("decimal", 1, "1.00", False, id="decimal-enum-does-not-coerce"),
    ],
)
def test_enum_checks_original_value_without_type_coercion(
    data_type: str, value: Any, allowed: str, valid: bool
) -> None:
    definition = ImportDefinition(
        "fixture",
        "测试",
        1,
        "fixture",
        (ImportField("value", "字段", 1, data_type=data_type, enum_values=(allowed,)),),
    )

    problems = validate_fields(definition, {"value": value})

    assert [problem.message for problem in problems] == ([] if valid else ["字段不在允许值范围内"])


@pytest.mark.parametrize(
    "rules,expected",
    [
        pytest.param(("trim", "lowercase", "uppercase"), "ABC", id="uppercase-last"),
        pytest.param(("trim", "uppercase", "lowercase"), "abc", id="lowercase-last"),
    ],
)
def test_normalization_keeps_declared_order_and_untouched_values(
    rules: tuple[str, ...], expected: str
) -> None:
    definition = ImportDefinition(
        "fixture",
        "测试",
        1,
        "fixture",
        (
            ImportField("code", "编码", 1, normalization_rules=rules),
            ImportField("count", "数量", 2, data_type="integer", normalization_rules=rules),
            ImportField("missing", "缺失字段", 3),
        ),
    )
    raw = {"code": " AbC ", "count": 1, "unmapped": " untouched "}

    assert normalize_fields(definition, raw) == {
        "code": expected,
        "count": 1,
        "missing": None,
        "unmapped": " untouched ",
    }
    assert raw == {"code": " AbC ", "count": 1, "unmapped": " untouched "}


def test_multiple_field_issues_follow_template_column_order() -> None:
    definition = ImportDefinition(
        "fixture",
        "测试",
        1,
        "fixture",
        (
            ImportField("first", "首列", 2, required=True),
            ImportField("second", "次列", 5, data_type="integer"),
        ),
    )

    problems = validate_fields(definition, {"second": "private-invalid"})

    assert [(problem.field_key, problem.column_index, problem.message) for problem in problems] == [
        ("first", 2, "必填字段不能为空"),
        ("second", 5, "字段类型不符合模板要求"),
    ]
