from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest


@pytest.mark.parametrize(
    ("service", "message", "ready"),
    [
        pytest.param(
            "worker", "worker_ready scheduler=running task_handlers=9", True, id="legacy-marker"
        ),
        pytest.param(
            "worker",
            "worker_ready scheduler=running task_handlers=9 task_sources=2 total_handlers=13",
            True,
            id="task-source-statistics",
        ),
        pytest.param(
            "worker", "worker_ready scheduler=running task_handlers=0", False, id="no-handlers"
        ),
        pytest.param(
            "worker",
            "worker_ready scheduler=running task_handlers=0 task_sources=2 total_handlers=4",
            False,
            id="no-payment-handlers",
        ),
        pytest.param(
            "worker", "worker_ready scheduler=running task_handlers=9x", False, id="invalid-count"
        ),
        pytest.param(
            "worker",
            "worker_ready scheduler=stopped task_handlers=9",
            False,
            id="scheduler-stopped",
        ),
        pytest.param(
            "platform", "worker_ready scheduler=running task_handlers=9", False, id="wrong-service"
        ),
    ],
)
def test_worker_readiness_marker(tmp_path: Path, service: str, message: str, ready: bool) -> None:
    from scripts.dev.runtime import LogTail, RunningService
    from scripts.dev.services import DEFAULT_TIMING, Service

    log = tmp_path / "worker.log"
    log.write_text(json.dumps({"service": service, "message": message}) + "\n")
    process = Mock(spec=subprocess.Popen)
    process.poll.return_value = None
    worker = RunningService(
        Service("worker", [], str(tmp_path), worker=True),
        process,
        tmp_path / "worker.events.json",
        LogTail(log),
    )

    worker.observe(DEFAULT_TIMING)

    assert worker.ready is ready
