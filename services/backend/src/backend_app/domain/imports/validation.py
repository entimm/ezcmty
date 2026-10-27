"""Declarative normalization and safe field diagnostics."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID

from pydantic import BeforeValidator, ConfigDict, Field, TypeAdapter, ValidationError

from backend_app.domain.imports.registry import ImportDefinition
from backend_app.domain.imports.types import ImportProblem

_CONFIG = ConfigDict(strict=True, hide_input_in_errors=True, regex_engine="python-re")
_Date = Annotated[date, BeforeValidator(lambda value: date.fromisoformat(str(value)))]
_Datetime = Annotated[datetime, BeforeValidator(lambda value: datetime.fromisoformat(str(value)))]


def _adapters(rules: dict[str, Any]) -> dict[str, TypeAdapter[Any]]:
    return {key: TypeAdapter(annotation, config=_CONFIG) for key, annotation in rules.items()}


# Keep the published ISO grammar and original values; default coercion also accepts timestamps.
_TYPE_ADAPTERS = _adapters(
    {
        "string": str,
        "integer": int | Annotated[str, Field(pattern=r"^[+-]?\d+\z")],
        "decimal": Annotated[
            Decimal, Field(strict=False, allow_inf_nan=False), BeforeValidator(str)
        ],
        "boolean": bool
        | Annotated[
            str,
            Field(pattern=r"^(true|false)\z"),
            BeforeValidator(lambda value: value.lower() if isinstance(value, str) else value),
        ],
        "date": _Date,
        "datetime": _Datetime,
    }
)
_FORMAT_ADAPTERS = _adapters(
    {
        "email": Annotated[
            str, Field(pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+\z"), BeforeValidator(str)
        ],
        "phone": Annotated[str, Field(pattern=r"^\+?[0-9 -]{6,32}\z"), BeforeValidator(str)],
        "mobile": Annotated[str, Field(pattern=r"^\+?[0-9 -]{6,32}\z"), BeforeValidator(str)],
        "uuid": Annotated[UUID, BeforeValidator(lambda value: UUID(str(value)))],
        "date": _Date,
        "date-time": _Datetime,
        "datetime": _Datetime,
    }
)


def normalize_fields(definition: ImportDefinition, values: dict[str, Any]) -> dict[str, Any]:
    result = dict(values)
    for field in definition.fields:
        value = result.get(field.key)
        if isinstance(value, str):
            for rule in field.normalization_rules:
                if rule == "trim":
                    value = value.strip()
                elif rule == "lowercase":
                    value = value.lower()
                elif rule == "uppercase":
                    value = value.upper()
        result[field.key] = value
    return result


def _matches(adapter: TypeAdapter[Any], value: Any) -> bool:
    try:
        adapter.validate_python(value)
    except ValidationError:
        return False
    return True


def validate_fields(definition: ImportDefinition, values: dict[str, Any]) -> list[ImportProblem]:
    issues: list[ImportProblem] = []
    for field in definition.fields:
        value = values.get(field.key)
        message: str | None = None
        if value is None or value == "":
            if field.required:
                message = "必填字段不能为空"
        elif not _matches(_TYPE_ADAPTERS[field.data_type], value):
            message = "字段类型不符合模板要求"
        elif field.max_length is not None and len(str(value)) > field.max_length:
            message = "字段超过允许长度"
        elif field.enum_values and value not in field.enum_values:
            message = "字段不在允许值范围内"
        elif field.format and not _matches(_FORMAT_ADAPTERS[field.format], value):
            message = "字段格式不符合模板要求"
        if message:
            issues.append(
                ImportProblem(
                    "import.validation_failed",
                    message,
                    field_key=field.key,
                    column_name=field.label,
                    column_index=field.order,
                )
            )
    return issues
