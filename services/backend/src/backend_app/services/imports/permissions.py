"""Business capability checks shared by import actions and Worker execution."""

from collections.abc import Mapping
from typing import Any

from sqlalchemy.orm import Session

from backend_app.core.errors import AppError
from backend_app.domain.imports.registry import ImportDefinition
from backend_app.domain.imports.validation import normalize_fields
from backend_app.models.imports import ImportBatch
from backend_app.repositories.imports.pipeline import iter_inputs
from backend_app.services.worker.imports.adapters.base import ImportAdapter


def prepared_values(snapshot: Mapping[str, Any] | None) -> dict[str, Any] | None:
    value = snapshot.get("_prepared") if snapshot is not None else None
    return value if isinstance(value, dict) else None


def source_values(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in snapshot.items() if key not in {"_prepared", "_identity"}}


def require_permissions(required: frozenset[str], permissions: frozenset[str]) -> None:
    if not required <= permissions:
        raise AppError("auth.forbidden")


def batch_permissions(
    db: Session, batch: ImportBatch, definition: ImportDefinition, adapter: ImportAdapter
) -> frozenset[str]:
    required: set[str] = set()
    for raw, normalized in iter_inputs(db, batch.id):
        if normalized is not None:
            source = source_values(normalized)
        elif raw is not None:
            source = adapter.normalize(normalize_fields(definition, raw))
        else:
            continue
        required.update(adapter.required_permissions(source, prepared_values(normalized)))
    return frozenset(required)
