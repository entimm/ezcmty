"""Observe Uvicorn's real children without reimplementing its reload watcher."""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from uvicorn import Config, Server
from uvicorn.supervisors.watchfilesreload import WatchFilesReload
from watchfiles import watch

from scripts.dev.processes import atomic_json, identity


class ObservedReload(WatchFilesReload):
    def __init__(self, config: Config, server: Server, event_file: Path) -> None:
        super().__init__(config, target=server.run, sockets=[config.bind_socket()])
        self.event_file = event_file
        self.observation_lock = threading.Lock()
        self.monitor_stop = threading.Event()
        self.restarting = False
        self.generation = 0
        self.reload_started: float | None = None
        self.failure = False
        self.watcher = watch(
            *self.reload_dirs,
            watch_filter=None,
            stop_event=self.should_exit,
            rust_timeout=100,
            yield_on_timeout=True,
            ignore_permission_denied=True,
        )

    def publish(self, phase: str, **extra: Any) -> None:
        pid = self.process.pid
        child = identity(pid) if pid is not None else None
        atomic_json(
            self.event_file,
            {
                "phase": phase,
                "generation": self.generation,
                "child": asdict(child) if child is not None else None,
                "parent": os.getpid(),
                "reload_started": self.reload_started,
                **extra,
            },
        )

    def acknowledge_readiness(self) -> None:
        try:
            acknowledgement = json.loads(self.event_file.with_suffix(".ack.json").read_text())
            if acknowledgement["generation"] == self.generation:
                self.reload_started = None
        except OSError, ValueError, KeyError, TypeError:
            pass

    def startup(self) -> None:
        # WatchFiles initializes lazily on first iteration. Arm its existing watcher
        # before the child can become ready, rather than losing the first quick edit.
        next(self.watcher)
        with self.observation_lock:
            super().startup()
            self.publish("started")
        self.monitor = threading.Thread(target=self.observe_child, daemon=True)
        self.monitor.start()

    def observe_child(self) -> None:
        while not self.monitor_stop.wait(0.1):
            with self.observation_lock:
                self.acknowledge_readiness()
                if self.should_exit.is_set():
                    return
                if not self.restarting and not self.process.is_alive():
                    # Exit code zero is also a failure unless we initiated shutdown/reload.
                    self.process.join(timeout=0)
                    self.failure = True
                    self.publish(
                        "failed", reason=f"实际 API 子进程意外退出（{self.process.exitcode}）"
                    )
                    self.should_exit.set()
                    return

    def restart(self) -> None:
        with self.observation_lock:
            if self.should_exit.is_set():
                return
            if not self.process.is_alive():
                self.failure = True
                self.publish("failed", reason="文件变更前实际 API 子进程已意外退出")
                self.should_exit.set()
                return
            self.acknowledge_readiness()
            self.restarting = True
            self.generation += 1
            # Preserve the first recovery deadline across repeated file changes.
            if self.reload_started is None:
                self.reload_started = time.monotonic()
            self.publish("reloading")
        # Uvicorn owns termination, join, and creation of the replacement child.
        # Keep the observer unlocked so the coordinator's deadline can stop a hung join.
        super().restart()
        with self.observation_lock:
            self.restarting = False
            self.publish("started")

    def shutdown(self) -> None:
        self.monitor_stop.set()
        super().shutdown()


def main() -> int:
    app, port = sys.argv[1:3]
    event_file = Path(os.environ["DEV_API_EVENT_FILE"])
    config = Config(
        app,
        host="127.0.0.1",
        port=int(port),
        reload=True,
        reload_dirs=[str(Path.cwd() / "src")],
        reload_delay=0.5,
        timeout_graceful_shutdown=10,
    )
    supervisor = ObservedReload(config, Server(config), event_file)
    try:
        supervisor.run()
    finally:
        for listener in supervisor.sockets:
            listener.close()
    return 1 if supervisor.failure else 0


if __name__ == "__main__":
    raise SystemExit(main())
