from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from sqlalchemy.orm import Session


class SourceLeaseLost(Exception):
    """The source rejected an expired or superseded task lease."""


@dataclass(frozen=True)
class TaskEnvelope:
    id: str
    task_type: str
    target_id: str
    attempt_count: int
    lease_expires_at: datetime


class TaskSource(Protocol):
    name: str
    task_count: int
    periodic_checks: Mapping[str, Callable[[], None]]

    def probe(self, db: Session) -> None: ...

    def claim(
        self, db: Session, *, now: datetime, lease_seconds: int
    ) -> tuple[TaskEnvelope, ...]: ...

    def renew(
        self, db: Session, lease: TaskEnvelope, *, now: datetime, lease_seconds: int
    ) -> None: ...

    def dispatch(self, lease: TaskEnvelope) -> None: ...

    def close(self) -> None: ...
