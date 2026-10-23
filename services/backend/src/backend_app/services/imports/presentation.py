"""Explicit adapter projections; internal preparation data never becomes an API object."""

from collections.abc import Mapping
from math import isfinite
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend_app.models.imports import ImportBatch, ImportRow
from backend_app.schemas.imports import ImportBusinessField, ImportBusinessSummary
from backend_app.services.imports.permissions import prepared_values


def fields(adapter: Any) -> list[dict[str, Any]] | None:
    declared = getattr(adapter, "presentation_fields", None)
    if not callable(declared):
        return None
    result = [ImportBusinessField.model_validate(field).model_dump() for field in declared()]
    if len({field["key"] for field in result}) != len(result):
        raise ValueError("import.adapter_result_invalid")
    return result


def values(adapter: Any, prepared: Mapping[str, Any] | None) -> dict[str, Any] | None:
    declared = fields(adapter)
    if prepared is None or declared is None:
        return None
    projected = adapter.presentation(prepared)
    result: dict[str, Any] = {}
    for field in declared:
        value = projected.get(field["key"])
        if value is not None and (
            type(value) not in {str, int, float, bool}
            or isinstance(value, float)
            and not isfinite(value)
        ):
            raise ValueError("import.adapter_result_invalid")
        if (
            field["format"] == "money_cents"
            and value is not None
            and (type(value) is not int or not 0 <= value <= 9007199254740991)
        ):
            raise ValueError("import.adapter_result_invalid")
        result[field["key"]] = value
    return result


def preview(db: Session, batch: ImportBatch, adapter: Any) -> dict[str, Any] | None:
    declared = fields(adapter)
    if declared is None:
        return None
    summaries = [
        ImportBusinessSummary.model_validate(
            {**field, "without_warning_rows": "0", "with_warning_rows": "0"}
        ).model_dump()
        for field in adapter.summary_fields()
    ]
    if len({field["key"] for field in summaries}) != len(summaries):
        raise ValueError("import.adapter_result_invalid")
    totals = {field["key"]: [0, 0] for field in summaries}
    rows = db.execute(
        select(ImportRow.normalized_values, ImportRow.warning_count)
        .where(
            ImportRow.batch_id == batch.id,
            ImportRow.validation_version == batch.preview_version,
            ImportRow.validation_status == "valid",
            ImportRow.planned_action == "create",
        )
        .execution_options(yield_per=200)
    )
    for normalized, warning_count in rows:
        prepared = prepared_values(cast(dict[str, Any] | None, normalized))
        if prepared is None:
            raise ValueError("import.adapter_result_invalid")
        projected = adapter.presentation(prepared)
        for key, total in totals.items():
            value = projected.get(key)
            if type(value) is not int or value < 0:
                raise ValueError("import.adapter_result_invalid")
            total[1] += value
            if warning_count == 0:
                total[0] += value
    for field in summaries:
        field["without_warning_rows"], field["with_warning_rows"] = map(str, totals[field["key"]])
    return {"fields": declared, "summary": summaries}
