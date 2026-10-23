from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from sqlalchemy.orm import Session

from backend_app.domain.imports.types import (
    ImportContext,
    ImportPlan,
    ImportPreparation,
    ImportProblem,
)


class ImportAdapter(Protocol):
    """Participates in the caller's transaction; never owns commits, leases or HTTP identity."""

    def normalize(self, row: Mapping[str, Any]) -> dict[str, Any]: ...

    def prepare(
        self,
        normalized_input: Mapping[str, Any],
        context: ImportContext,
        db: Session,
        *,
        fixed_prepared: Mapping[str, Any] | None = None,
    ) -> ImportPreparation: ...

    def required_permissions(
        self, normalized_input: Mapping[str, Any], prepared: Mapping[str, Any] | None = None
    ) -> frozenset[str]: ...

    def plan(self, prepared: Mapping[str, Any]) -> ImportPlan: ...

    def revalidate(
        self,
        prepared: Mapping[str, Any],
        context: ImportContext,
        db: Session,
        *,
        target: Mapping[str, str] | None = None,
    ) -> Sequence[ImportProblem]: ...

    def execute(
        self, operation: ImportPlan, context: ImportContext, db: Session
    ) -> Mapping[str, Any]: ...

    def resolve_operation(
        self,
        operation_key: str,
        prepared: Mapping[str, Any],
        context: ImportContext,
        db: Session,
    ) -> Mapping[str, Any] | None: ...
