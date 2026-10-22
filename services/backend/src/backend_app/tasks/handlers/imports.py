from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from backend_app.repositories.imports.tasks import TaskLease

IMPORT_TASK_PHASES = {
    "import_parse": "parse",
    "import_precheck": "precheck",
    "import_execute": "apply",
    "import_error_file": "artifact",
}


@dataclass(frozen=True)
class ImportHandlers:
    tasks: Mapping[str, Callable[[TaskLease], None]]
    periodic_checks: Mapping[str, Callable[[], None]] = field(default_factory=dict)
    on_close: Callable[[], None] | None = None

    def __post_init__(self) -> None:
        if not self.tasks or set(self.tasks) - IMPORT_TASK_PHASES.keys():
            raise ValueError("Worker requires registered import task handlers")

    def dispatch(self, lease: TaskLease) -> None:
        task_type = next(key for key, phase in IMPORT_TASK_PHASES.items() if phase == lease.phase)
        self.tasks[task_type](lease)
