from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from sqlalchemy.orm import Session

from backend_app.domain.imports.types import ImportContext, ImportPlan, ImportProblem


class ImportAdapter(Protocol):
    """Participates in the caller's transaction; never owns commits, leases or HTTP identity."""

    def normalize(self, row: Mapping[str, Any]) -> dict[str, Any]: ...

    def precheck(
        self, normalized_row: Mapping[str, Any], context: ImportContext, db: Session
    ) -> Sequence[ImportProblem]: ...

    def build_operation_key(self, row: Mapping[str, Any]) -> str: ...

    def plan(self, row: Mapping[str, Any]) -> ImportPlan: ...

    def execute(
        self, operation: ImportPlan, context: ImportContext, db: Session
    ) -> Mapping[str, Any]: ...
