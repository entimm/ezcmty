"""Subprocess fixtures for lifecycle tests; never used by development commands."""

from __future__ import annotations

import json
import os
import signal
import sys
import time
from pathlib import Path
from threading import Event


def main() -> int:
    if os.environ.get("DEV_TEST_TERMINAL") == "1":
        import fcntl
        import termios

        fcntl.ioctl(sys.stdin.fileno(), termios.TIOCSCTTY, 0)
    mode = sys.argv[1]
    if mode in ("client", "stop"):
        from scripts.dev.processes import DevError, Registry
        from scripts.dev.runtime import attach, launch, stop_all
        from scripts.dev.services import Service, Timing

        registry = Registry(Path(sys.argv[2]))
        request = json.loads(Path(sys.argv[3]).read_text())
        timing = Timing(**request["timing"])
        if mode == "stop":
            return stop_all(registry, timing)
        selected = [Service(**value) for value in request["services"]]
        try:
            batch_id, process = launch(
                registry,
                selected,
                sys.argv[4] == "background",
                preflight=request.get("preflight"),
                preflight_cwd=registry.root,
                timing=timing,
            )
            return attach(
                registry, batch_id, process, selected, sys.argv[4] == "background", timing
            )
        except DevError as exc:
            print(str(exc), flush=True)
            return 1
    if mode == "dependencies":
        state = Path(sys.argv[2]).read_text()
        print(json.dumps({"ok": state == "ok", "reason": state, "log_level": "INFO"}), flush=True)
        return 0
    if mode in {"worker", "stubborn-worker"}:
        stop = Event()
        signal.signal(
            signal.SIGTERM, signal.SIG_IGN if mode == "stubborn-worker" else lambda *_: stop.set()
        )
        signal.signal(signal.SIGINT, lambda *_: stop.set())
        print(
            json.dumps(
                {"service": "worker", "message": "worker_ready scheduler=running task_handlers=1"}
            ),
            flush=True,
        )
        stop.wait()
        return 0
    if mode == "exit":
        time.sleep(float(sys.argv[2]))
        return int(sys.argv[3])
    raise ValueError(mode)


if __name__ == "__main__":
    raise SystemExit(main())
