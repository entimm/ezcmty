"""Declarative normalization and safe field diagnostics."""

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from backend_app.domain.imports.registry import ImportDefinition, ImportField
from backend_app.domain.imports.types import ImportProblem


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


def _valid_type(field: ImportField, value: Any) -> bool:
    if field.data_type == "string":
        return isinstance(value, str)
    if field.data_type == "integer":
        return (
            type(value) is int or isinstance(value, str) and bool(re.fullmatch(r"[+-]?\d+", value))
        )
    if field.data_type == "decimal":
        try:
            return not isinstance(value, bool) and Decimal(str(value)).is_finite()
        except InvalidOperation:
            return False
    if field.data_type == "boolean":
        return type(value) is bool or isinstance(value, str) and value.lower() in {"true", "false"}
    try:
        if field.data_type == "date":
            date.fromisoformat(str(value))
        elif field.data_type == "datetime":
            datetime.fromisoformat(str(value))
        else:
            return False
    except ValueError:
        return False
    return True


def _valid_format(format_name: str, value: Any) -> bool:
    if format_name == "email":
        return bool(re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", str(value)))
    if format_name in {"phone", "mobile"}:
        return bool(re.fullmatch(r"\+?[0-9 -]{6,32}", str(value)))
    try:
        if format_name == "uuid":
            UUID(str(value))
        elif format_name == "date":
            date.fromisoformat(str(value))
        elif format_name in {"date-time", "datetime"}:
            datetime.fromisoformat(str(value))
        else:
            return False
    except ValueError:
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
        elif not _valid_type(field, value):
            message = "字段类型不符合模板要求"
        elif field.max_length is not None and len(str(value)) > field.max_length:
            message = "字段超过允许长度"
        elif field.enum_values and value not in field.enum_values:
            message = "字段不在允许值范围内"
        elif field.format and not _valid_format(field.format, value):
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
