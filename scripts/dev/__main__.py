"""CLI for the repository Makefile; all service targets use the same lifecycle."""

from __future__ import annotations

import argparse
import signal
import sys
import threading
from pathlib import Path

from scripts.dev.processes import DevError, Registry
from scripts.dev.runtime import announce, attach, coordinate, launch, stop_all
from scripts.dev.services import services

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    parser = argparse.ArgumentParser(description="本仓库的本地开发进程管理")
    commands = parser.add_subparsers(dest="action", required=True)
    start = commands.add_parser("start", help="启动一个批次")
    start.add_argument("services", nargs="+")
    start.add_argument("--background", action="store_true")
    commands.add_parser("stop", help="停止本仓库登记的所有批次")
    internal = commands.add_parser("_coordinate", help=argparse.SUPPRESS)
    internal.add_argument("root", type=Path)
    internal.add_argument("batch")
    options = parser.parse_args()
    try:
        if options.action == "_coordinate":
            return coordinate(Registry(options.root), options.batch)
        registry = Registry(ROOT)
        if options.action == "stop":
            return stop_all(registry)
        selected = services(ROOT, options.services)
        backend = ROOT / "services" / "backend"
        preflight = (
            [sys.executable, "-m", "scripts.dev.services", "dependencies"]
            if any(service.expected_service is not None or service.worker for service in selected)
            else None
        )
        cancelled = threading.Event()
        previous = {
            number: signal.signal(number, lambda *_: cancelled.set())
            for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
        }
        try:
            if cancelled.is_set():
                return 0
            batch, process = launch(
                registry,
                selected,
                options.background,
                preflight=preflight,
                preflight_cwd=backend,
            )
            return attach(
                registry, batch, process, selected, options.background, stop_event=cancelled
            )
        finally:
            for number, handler in previous.items():
                signal.signal(number, handler)
    except DevError as exc:
        announce(f"失败：{exc}")
        return 1
    except OSError as exc:
        announce(f"启动器无法执行本地操作（{type(exc).__name__}）；请检查依赖安装和目录权限。")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
