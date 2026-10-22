"""Batch state rules and row-selection semantics."""

TERMINAL_STATUSES = frozenset({"completed", "partial_failed", "failed", "cancelled", "expired"})
BATCH_STATUSES = TERMINAL_STATUSES | {
    "draft",
    "uploading",
    "prechecking",
    "preview_ready",
    "executing",
    "blocked",
    "cancel_requested",
}
TASK_PHASES = ("parse", "precheck", "apply", "artifact")
TASK_STATUSES = frozenset({"ready", "running", "completed", "paused", "cancelled"})
TRANSITIONS = {
    "draft": {"uploading", "prechecking", "cancelled", "expired", "blocked"},
    "uploading": {"draft", "prechecking", "cancelled", "expired", "blocked"},
    "prechecking": {"preview_ready", "failed", "blocked", "cancel_requested", "cancelled"},
    "preview_ready": {
        "prechecking",
        "executing",
        "cancel_requested",
        "cancelled",
        "expired",
        "blocked",
    },
    "executing": {"completed", "partial_failed", "failed", "blocked", "cancel_requested"},
    "blocked": {"prechecking", "executing", "cancel_requested", "cancelled", "failed", "expired"},
    "cancel_requested": {"cancelled", "blocked"},
}


def validate_transition(current: str, target: str, *, uncertain_rows: int = 0) -> None:
    if target not in BATCH_STATUSES or target not in TRANSITIONS.get(current, set()):
        raise ValueError("Invalid import batch transition")
    if uncertain_rows and target in TERMINAL_STATUSES:
        raise ValueError("Unknown import outcomes must be resolved before finishing")


def selected_row(*, validation_status: str, warning_count: int, include_warning_rows: bool) -> bool:
    return validation_status == "valid" and (warning_count == 0 or include_warning_rows)
