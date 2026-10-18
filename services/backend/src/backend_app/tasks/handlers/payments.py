from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from backend_app.repositories.payments.tasks import TASK_TARGETS, TaskLease

type TaskHandler = Callable[[TaskLease], None]
type PeriodicCheck = Callable[[], None]


@dataclass(frozen=True)
class PaymentHandlers:
    """Only concrete use cases are registered; missing handlers never complete tasks."""

    tasks: Mapping[str, TaskHandler]
    periodic_checks: Mapping[str, PeriodicCheck] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.tasks or set(self.tasks) - TASK_TARGETS.keys():
            raise ValueError("Worker requires registered payment task handlers")

    def dispatch(self, lease: TaskLease) -> None:
        self.tasks[lease.task_type](lease)
