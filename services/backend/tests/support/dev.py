from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from scripts.dev.processes import Registry
    from scripts.dev.services import Service, Timing

from tests.support.paths import REPOSITORY_ROOT

ROOT = REPOSITORY_ROOT
HELPER = Path(__file__).with_name("dev_helpers.py")


def eventually(predicate: Callable[[], bool], seconds: float = 12) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    assert predicate(), "lifecycle condition did not complete before its deadline"


def free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


@dataclass
class Harness:
    registry: Registry
    timing: Timing
    source: Path
    processes: list[subprocess.Popen[bytes]] = field(default_factory=list)
    terminals: list[int] = field(default_factory=list)

    def close(self) -> None:
        from scripts.dev.runtime import stop_all

        def close_process(process: subprocess.Popen[bytes]) -> None:
            try:
                if process.poll() is None:
                    process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            finally:
                if process.stdout is not None:
                    process.stdout.close()

        with ExitStack() as cleanup:
            for process in self.processes:
                cleanup.callback(close_process, process)
            for terminal in self.terminals:
                cleanup.callback(os.close, terminal)
            stop_all(self.registry, self.timing)

    def api(self, name: str = "platform", *, mode: str = "ok") -> Service:
        from scripts.dev.services import Service

        module = f"fixture_{name}"
        (self.source / f"{name}.mode").write_text(mode)
        (self.source / f"{module}.py").write_text(
            "import time\n"
            "from pathlib import Path\n"
            "from backend_app.app_factory import create_app\n"
            "from backend_app.core import system_routes\n"
            f"MODE = Path(__file__).with_name('{name}.mode')\n"
            "def dependencies():\n"
            "    value = MODE.read_text()\n"
            "    if value == 'slow':\n"
            "        time.sleep(2)\n"
            "    return {'mysql': 'ok' if value != 'unavailable' else 'unavailable', "
            "'redis': 'ok'}\n"
            "system_routes.check_readiness = dependencies\n"
            f"app = create_app('{name}-fixture-api')\n"
        )
        port = free_port()
        return Service(
            name,
            [sys.executable, "-m", "scripts.dev.api", f"{module}:app", str(port)],
            str(self.source.parent),
            port,
            f"{name}-fixture-api",
        )

    def worker(self, name: str = "worker", *, stubborn: bool = False) -> Service:
        from scripts.dev.services import Service

        command = [sys.executable, "-m", "backend_app.runtimes.worker"]
        if stubborn:
            command = [sys.executable, str(HELPER), "stubborn-worker"]
        return Service(name, command, str(self.source.parent), worker=True)

    def admin(self) -> Service:
        from scripts.dev.services import services

        service = services(ROOT, ["admin"])[0]
        project = ROOT / "apps" / "admin-web"
        if not (project / "node_modules" / "@umijs" / "max" / "bin" / "max.js").is_file():
            pytest.skip("Umi dependencies are not installed; run make install")
        port = free_port()
        # Exercise the real Umi process with an isolated frontend and listener.
        fixture = self.registry.root / "admin"
        (fixture / "src").mkdir(parents=True)
        (fixture / "node_modules").symlink_to(project / "node_modules", target_is_directory=True)
        (fixture / "package.json").write_text((project / "package.json").read_text())
        (fixture / "src" / "Home.tsx").write_text(
            "export default function Home() { return <main>Admin fixture</main>; }\n"
        )
        plugin = project / "config" / "plugins" / "dev-server.ts"
        (fixture / "dev-server.ts").write_text(
            f"import {{ configureDevServer }} from {json.dumps(str(plugin))};\n"
            f"export default function plugin(api) {{ configureDevServer(api, {port}); }}\n"
        )
        (fixture / ".umirc.ts").write_text(
            "export default { layout: false, antd: false, mfsu: false, "
            "routes: [{ path: '/', component: '@/Home' }], plugins: ['./dev-server.ts'] };\n"
        )
        self.timing = replace(self.timing, startup=60)
        return replace(service, cwd=str(fixture), port=port)

    def start(
        self,
        selected: list[Service],
        *,
        preflight: list[str] | None = None,
        timing: Timing | None = None,
    ) -> tuple[str, subprocess.Popen[bytes]]:
        from scripts.dev.runtime import launch

        batch, process = launch(
            self.registry,
            selected,
            True,
            preflight=preflight,
            preflight_cwd=self.registry.root,
            timing=timing or self.timing,
        )
        self.processes.append(process)
        return batch, process

    def ready(self, batch: str) -> None:
        def completed() -> bool:
            state = self.registry.read_batch(batch)
            if state["status"] == "failed":
                pytest.fail(
                    state["reason"]
                    + "\n"
                    + (self.registry.batch_directory(batch) / "coordinator.log").read_text()
                )
            return bool(state["status"] == "running")

        eventually(completed, seconds=max(12, self.timing.startup))

    def client(
        self,
        selected: list[Service],
        *,
        background: bool = True,
        mode: str = "client",
        terminal: bool = False,
    ) -> subprocess.Popen[bytes]:
        from scripts.dev.processes import subprocess_environment

        request = self.registry.root / f"client-{len(self.processes)}.json"
        request.write_text(
            json.dumps(
                {
                    "services": [asdict(service) for service in selected],
                    "timing": asdict(self.timing),
                }
            )
        )
        arguments = [sys.executable, str(HELPER), mode, str(self.registry.root), str(request)]
        if mode == "client":
            arguments.append("background" if background else "foreground")
        environment = subprocess_environment()
        stdin = subprocess.DEVNULL
        if terminal:
            master, stdin = os.openpty()
            self.terminals.append(master)
            environment["DEV_TEST_TERMINAL"] = "1"
        process = subprocess.Popen(
            arguments,
            env=environment,
            stdin=stdin,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        if terminal:
            os.close(stdin)
        self.processes.append(process)
        return process


def assert_ports_released(selected: list[Service]) -> None:
    from scripts.dev.services import check_ports

    check_ports(selected)
