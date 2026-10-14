"""Exercise ownership, readiness and reloads with real isolated subprocesses."""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
from collections.abc import Callable, Generator
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from pytest import MonkeyPatch

if TYPE_CHECKING:
    from scripts.dev.processes import Registry
    from scripts.dev.services import Service, Timing

ROOT = Path(__file__).resolve().parents[4]
HELPER = Path(__file__).resolve().parents[1] / "dev_helpers.py"


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


@pytest.fixture
def harness(tmp_path: Path, monkeypatch: MonkeyPatch) -> Generator[Harness]:
    monkeypatch.syspath_prepend(str(ROOT))
    from scripts.dev.processes import Registry
    from scripts.dev.runtime import stop_all
    from scripts.dev.services import Timing

    source = tmp_path / "backend" / "src"
    source.mkdir(parents=True)
    monkeypatch.setenv("PYTHONPATH", str(source))
    monkeypatch.setenv("APP_LOG_LEVEL", "INFO")
    result = Harness(
        Registry(tmp_path),
        Timing(startup=8, probe=2, interval=0.1, graceful=1, forced=2, reload=4),
        source,
    )
    yield result
    stop_all(result.registry, result.timing)
    for terminal in result.terminals:
        os.close(terminal)
    for process in result.processes:
        if process.poll() is None:
            process.send_signal(signal.SIGTERM)
        process.wait(timeout=5)
        if process.stdout is not None:
            process.stdout.close()


def assert_ports_released(selected: list[Service]) -> None:
    from scripts.dev.services import check_ports

    check_ports(selected)


def test_all_services_start_and_stop(harness: Harness) -> None:
    from scripts.dev.runtime import stop_all

    selected = [harness.api(name) for name in ("platform", "property", "resident", "webhook")]
    selected.append(harness.worker())
    selected.append(harness.admin())
    batch, coordinator = harness.start(selected)
    harness.ready(batch)
    state = harness.registry.read_batch(batch)
    assert all(value["ready"] for value in state["services"].values())
    assert "task_handlers=0" in state["services"]["worker"]["reason"]
    assert stop_all(harness.registry, harness.timing) == 0
    coordinator.wait(timeout=5)
    assert_ports_released(selected)
    assert stop_all(harness.registry, harness.timing) == 0
    next_batch, _ = harness.start([selected[0]])
    harness.ready(next_batch)


@pytest.mark.parametrize("name", ["platform", "property", "resident", "webhook", "worker"])
def test_individual_services_share_the_lifecycle(harness: Harness, name: str) -> None:
    selected = [harness.worker() if name == "worker" else harness.api(name)]
    batch, coordinator = harness.start(selected)
    harness.ready(batch)
    harness.registry.request_stop(batch)
    assert coordinator.wait(timeout=5) == 0
    assert_ports_released(selected)


def test_duplicate_and_mixed_start_reject_whole_request(harness: Harness) -> None:
    from scripts.dev.processes import DevError, is_alive

    platform = harness.api()
    batch, _ = harness.start([platform])
    # The starting reservation is already exclusive, before readiness.
    with pytest.raises(DevError, match="已有实例"):
        harness.start([platform, harness.worker()])
    harness.ready(batch)
    before = harness.registry.read_batch(batch)
    with pytest.raises(DevError, match="make stop"):
        harness.start([platform])
    assert is_alive(before["processes"]["platform"]["root"])
    with harness.registry.locked() as state:
        assert list(state["batches"]) == [batch]


def test_failed_batch_does_not_stop_prior_independent_batch(harness: Harness) -> None:
    from scripts.dev.processes import is_alive
    from scripts.dev.services import Service

    existing, _ = harness.start([harness.worker("independent")])
    harness.ready(existing)
    broken = Service(
        "broken", [sys.executable, str(HELPER), "exit", "0.8", "0"], str(harness.registry.root)
    )
    api = harness.api()
    failed, coordinator = harness.start([api, broken])
    assert coordinator.wait(timeout=12) != 0
    assert harness.registry.read_batch(failed)["status"] == "failed"
    assert is_alive(harness.registry.read_batch(existing)["processes"]["independent"]["root"])
    assert_ports_released([api])


def test_port_conflict_preserves_external_listener(harness: Harness) -> None:
    from scripts.dev.processes import DevError

    service = harness.api()
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", service.port))
        listener.listen()
        with pytest.raises(DevError, match="端口"):
            harness.start([service])
        assert listener.fileno() >= 0
    with harness.registry.locked() as state:
        assert not state["batches"]


@pytest.mark.parametrize("mode", ["unavailable", "slow"])
def test_readiness_retries_timeout_and_batch_cleanup(harness: Harness, mode: str) -> None:
    from scripts.dev.services import Timing

    selected = [harness.api(mode=mode), harness.worker()]
    timing = Timing(startup=3, probe=0.3, interval=0.1, graceful=1, forced=2, reload=4)
    batch, process = harness.start(selected, timing=timing)
    assert process.wait(timeout=10) != 0
    final = harness.registry.read_batch(batch)
    assert "启动总超时" in final["reason"]
    assert "HTTP 503" in final["reason"] if mode == "unavailable" else "超时" in final["reason"]
    assert_ports_released(selected)


def test_dependency_retry_then_worker_marker(harness: Harness) -> None:
    flag = harness.registry.root / "dependencies.mode"
    flag.write_text("依赖暂不可用")
    command = [sys.executable, str(HELPER), "dependencies", str(flag)]
    batch, _ = harness.start([harness.worker()], preflight=command)
    eventually(lambda: "probe-dependencies" in harness.registry.read_batch(batch)["processes"])
    assert "worker" not in harness.registry.read_batch(batch)["processes"]
    flag.write_text("ok")
    harness.ready(batch)


def test_completed_probe_after_deadline_cannot_report_ready(harness: Harness) -> None:
    from scripts.dev.runtime import Probe

    batch, _ = harness.start([harness.worker()])
    harness.ready(batch)
    command = [
        sys.executable,
        "-c",
        "import json,time; time.sleep(0.2); "
        "print(json.dumps({'ok':True,'reason':'late','finished':time.monotonic()}))",
    ]
    probe = Probe.start(
        harness.registry,
        batch,
        "late",
        command,
        harness.registry.root,
        replace(harness.timing, probe=0.1),
    )
    probe.process.wait(timeout=3)
    result = probe.result(time.monotonic())
    assert result is not None and not result["ok"] and "超时" in result["reason"]


def test_api_retries_readiness_until_dependencies_recover(harness: Harness) -> None:
    service = harness.api(mode="unavailable")
    batch, _ = harness.start([service])
    eventually(
        lambda: (
            "HTTP 503"
            in harness.registry.read_batch(batch)["services"].get("platform", {}).get("reason", "")
        )
    )
    (harness.source / "platform.mode").write_text("ok")
    harness.ready(batch)
    assert harness.registry.read_batch(batch)["services"]["platform"]["generation"] == 0


def test_worker_liveness_without_start_marker_is_not_ready(harness: Harness) -> None:
    from scripts.dev.services import Service

    worker = Service(
        "worker",
        [sys.executable, str(HELPER), "exit", "30", "0"],
        str(harness.registry.root),
        worker=True,
    )
    batch, coordinator = harness.start([worker], timing=replace(harness.timing, startup=2))
    assert coordinator.wait(timeout=8) != 0
    assert "启动总超时" in harness.registry.read_batch(batch)["reason"]


def test_normal_reload_repeated_recovery_and_child_crash(harness: Harness) -> None:
    from scripts.dev.processes import is_alive, signal_owned

    selected = [harness.api(), harness.worker()]
    batch, coordinator = harness.start(selected)
    harness.ready(batch)
    previous = harness.registry.read_batch(batch)["services"]["platform"]["child"]
    source = harness.source / "fixture_platform.py"
    for generation in (1, 2):
        source.write_text(source.read_text() + f"\n# reload {generation}\n")

        def generation_reached(expected: int = generation) -> bool:
            return bool(
                harness.registry.read_batch(batch)["services"]["platform"]["generation"] >= expected
            )

        eventually(generation_reached)
        eventually(lambda: harness.registry.read_batch(batch)["services"]["platform"]["ready"])
        current = harness.registry.read_batch(batch)["services"]["platform"]["child"]
        assert current["pid"] != previous["pid"]
        assert not is_alive(previous)
        previous = current
        assert coordinator.poll() is None
    parent = harness.registry.read_batch(batch)["processes"]["platform"]["root"]
    signal_owned(previous, signal.SIGTERM)
    assert is_alive(parent), "the reloader parent must still be alive at child failure"
    assert coordinator.wait(timeout=12) != 0
    assert "实际 API 子进程" in harness.registry.read_batch(batch)["reason"]
    assert_ports_released(selected)


def test_reload_recovery_timeout_stops_siblings(harness: Harness) -> None:
    selected = [harness.api(), harness.worker()]
    batch, coordinator = harness.start(selected)
    harness.ready(batch)
    (harness.source / "platform.mode").write_text("unavailable")
    source = harness.source / "fixture_platform.py"
    source.write_text(source.read_text() + "\n# dependencies become unavailable during reload\n")
    assert coordinator.wait(timeout=12) != 0
    assert "热重载后" in harness.registry.read_batch(batch)["reason"]
    assert_ports_released(selected)


def test_new_reload_child_exit_is_failure(harness: Harness) -> None:
    from scripts.dev.processes import is_alive

    independent, _ = harness.start([harness.worker("independent")])
    harness.ready(independent)
    selected = [harness.api(), harness.worker()]
    batch, coordinator = harness.start(selected)
    harness.ready(batch)
    (harness.source / "fixture_platform.py").write_text(
        "raise RuntimeError('fixture import fails')\n"
    )
    assert coordinator.wait(timeout=12) != 0
    assert "子进程" in harness.registry.read_batch(batch)["reason"]
    assert_ports_released(selected)
    assert is_alive(harness.registry.read_batch(independent)["processes"]["independent"]["root"])


def test_foreground_signal_only_stops_its_batch(harness: Harness) -> None:
    from scripts.dev.processes import is_alive

    existing, _ = harness.start([harness.worker("independent")])
    harness.ready(existing)
    service = harness.api()
    client = harness.client([service], background=False)

    def foreground_ready() -> bool:
        with harness.registry.locked() as state:
            return any(
                batch["requested"] == ["platform"] and batch["status"] == "running"
                for batch in state["batches"].values()
            )

    eventually(foreground_ready)
    client.send_signal(signal.SIGINT)
    assert client.wait(timeout=8) == 0
    assert_ports_released([service])
    assert is_alive(harness.registry.read_batch(existing)["processes"]["independent"]["root"])


def test_background_outlives_launcher_and_has_no_terminal(harness: Harness) -> None:
    from scripts.dev.processes import is_alive
    from scripts.dev.services import http_probe

    service = harness.api()
    client = harness.client([service], terminal=True)
    output, _ = client.communicate(timeout=12)
    assert client.returncode == 0, output.decode()
    with harness.registry.locked() as state:
        batch = next(iter(state["batches"].values()))
        coordinator = batch["coordinator"]
        root = batch["processes"]["platform"]["root"]
    assert is_alive(coordinator) and is_alive(root)
    assert os.getsid(coordinator["pid"]) == coordinator["pid"]
    assert os.getsid(root["pid"]) == root["pid"]
    assert root["pgid"] != client.pid
    os.close(harness.terminals.pop())
    time.sleep(0.2)
    assert http_probe(service, 1)["ok"]


def test_admin_runs_without_backend_configuration(
    harness: Harness, monkeypatch: MonkeyPatch
) -> None:
    from scripts.dev.processes import is_alive
    from scripts.dev.services import http_probe

    monkeypatch.delenv("APP_DATABASE_URL")
    monkeypatch.delenv("APP_REDIS_URL")
    service = harness.admin()
    batch, coordinator = harness.start([service])
    harness.ready(batch)
    assert http_probe(service, 1)["ok"]
    members = harness.registry.read_batch(batch)["processes"]["admin"]["members"]
    harness.registry.request_stop(batch)
    assert coordinator.wait(timeout=6) == 0
    assert not any(is_alive(member) for member in members)
    assert_ports_released([service])


def test_admin_missing_dependency_is_rejected_before_registration(harness: Harness) -> None:
    from scripts.dev.processes import DevError
    from scripts.dev.services import services

    uninstalled = harness.registry.root / "uninstalled-admin"
    uninstalled.mkdir()
    service = replace(services(ROOT, ["admin"])[0], cwd=str(uninstalled))
    with pytest.raises(DevError, match="管理后台依赖未安装"):
        harness.start([service])
    with harness.registry.locked() as state:
        assert not state["batches"]


def test_admin_cli_port_conflict_returns_failure(harness: Harness) -> None:
    from scripts.dev.processes import subprocess_environment

    service = harness.admin()
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", service.port))
        listener.listen()
        process = subprocess.Popen(
            service.command,
            cwd=service.cwd,
            env=subprocess_environment(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        harness.processes.append(process)
        output, _ = process.communicate(timeout=30)
        assert process.returncode == 1, output.decode()
        assert "已被占用" in output.decode()
        assert "不会自动切换端口" in output.decode()


def test_concurrent_launches_accept_only_one_batch(harness: Harness) -> None:
    service = harness.api()
    first = harness.client([service])
    second = harness.client([service])
    outputs = [process.communicate(timeout=15)[0] for process in (first, second)]
    assert sorted([first.returncode, second.returncode]) == [0, 1], outputs
    with harness.registry.locked() as state:
        assert len(state["batches"]) == 1


def test_start_rejected_while_stop_is_in_progress(harness: Harness) -> None:
    from scripts.dev.processes import DevError

    batch, _ = harness.start([harness.worker(stubborn=True)])
    harness.ready(batch)
    stopper = harness.client([], mode="stop")

    def stopping() -> bool:
        with harness.registry.locked() as state:
            return bool(state["stopping"] is not None)

    eventually(stopping)
    with pytest.raises(DevError, match="正在执行 make stop"):
        harness.start([harness.api()])
    assert stopper.wait(timeout=8) == 0
    with harness.registry.locked() as state:
        assert not state["batches"] and state["stopping"] is None


def test_stop_cancels_batch_during_dependency_check(harness: Harness) -> None:
    from scripts.dev.runtime import stop_all

    flag = harness.registry.root / "dependencies.mode"
    flag.write_text("not-ready")
    selected = [harness.worker()]
    batch, coordinator = harness.start(
        selected,
        preflight=[sys.executable, str(HELPER), "dependencies", str(flag)],
    )
    eventually(lambda: "probe-dependencies" in harness.registry.read_batch(batch)["processes"])
    assert stop_all(harness.registry, harness.timing) == 0
    coordinator.wait(timeout=5)
    assert "worker" not in harness.registry.read_batch(batch)["processes"]


def test_stale_identity_never_signals_reused_pid(harness: Harness) -> None:
    from scripts.dev.processes import identity
    from scripts.dev.runtime import stop_all

    external = subprocess.Popen(
        [sys.executable, str(HELPER), "exit", "30", "0"], start_new_session=True
    )
    try:
        actual = identity(external.pid)
        assert actual is not None
        stale = {**asdict(actual), "started": actual.started - 1}
        batch_id = "f" * 32
        with harness.registry.locked() as state:
            state["batches"][batch_id] = {
                "id": batch_id,
                "requested": ["platform"],
                "status": "running",
                "coordinator": None,
                "processes": {"platform": {"root": stale, "members": [stale]}},
            }
        assert stop_all(harness.registry, harness.timing) == 0
        assert external.poll() is None
        with harness.registry.locked() as state:
            assert not state["batches"]
    finally:
        external.terminate()
        external.wait(timeout=5)


def test_explicit_backend_env_and_environment_priority(
    harness: Harness,
    monkeypatch: MonkeyPatch,
) -> None:
    from scripts.dev.services import dependency_probe

    from backend_app.core import readiness as system
    from backend_app.core.config import get_settings

    backend = harness.source.parent
    (backend / ".env").write_text(
        "APP_DATABASE_URL=mysql+pymysql://env-user:secret@127.0.0.1/existing\n"
        "APP_REDIS_URL=redis://127.0.0.1:6379/4\n"
    )
    (harness.registry.root / ".env").write_text("APP_DATABASE_URL=wrong-root-file\n")
    monkeypatch.delenv("APP_DATABASE_URL")
    monkeypatch.delenv("APP_REDIS_URL")
    monkeypatch.chdir(backend)
    monkeypatch.setattr(system, "check_readiness", lambda: {"mysql": "ok", "redis": "ok"})
    get_settings.cache_clear()
    assert dependency_probe()["ok"]
    assert get_settings().redis_url.get_secret_value().endswith("/4")
    monkeypatch.setenv("APP_REDIS_URL", "redis://127.0.0.1:6379/9")
    get_settings.cache_clear()
    assert dependency_probe()["ok"]
    assert get_settings().redis_url.get_secret_value().endswith("/9")
    assert "secret" not in json.dumps(dependency_probe())


def test_service_mapping_ports_umi_and_readiness_identity(harness: Harness) -> None:
    from scripts.dev.services import http_probe, services

    definitions = services(ROOT, ["all"])
    assert [service.port for service in definitions] == [8001, 8002, 8003, 8004, None, 5173]
    assert definitions[-1].command[1].endswith("apps/admin-web/scripts/dev.cjs")
    assert len(definitions[-1].command) == 2
    selected = [harness.api()]
    batch, _ = harness.start(selected)
    harness.ready(batch)
    wrong = type(selected[0])(**{**asdict(selected[0]), "expected_service": "wrong-service"})
    assert not http_probe(wrong, 1)["ok"]
