"""Plain import domain values, independent of HTTP and persistence."""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ImportScope:
    property_company_id: str
    scope_type: str
    community_id: str | None = None
    snapshot: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.scope_type not in {"company", "community"}:
            raise ValueError("Unsupported import scope")
        if (self.scope_type == "company") != (self.community_id is None):
            raise ValueError("Import scope and community do not match")


@dataclass(frozen=True)
class ImportContext:
    actor_scope: str
    actor_id: str
    scope: ImportScope
    request_id: str
    permissions: frozenset[str] = frozenset()


@dataclass(frozen=True)
class ImportPlan:
    action: str
    values: dict[str, Any] = field(default_factory=dict)
    operation_type: str | None = None
    natural_key: dict[str, Any] | None = None
    input_fingerprint: str | None = None


@dataclass(frozen=True)
class ImportProblem:
    code: str
    message: str
    severity: str = "error"
    field_key: str | None = None
    column_name: str | None = None
    column_index: int | None = None
    cell_reference: str | None = None
    suggestion: str | None = None
    detail: dict[str, Any] | None = None
