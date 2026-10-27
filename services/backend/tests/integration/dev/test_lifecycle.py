from __future__ import annotations

import os
import signal
import socket
import subprocess
import time
from dataclasses import asdict, replace

import pytest
from pytest import MonkeyPatch
from tests.support.dev import ROOT, Harness, assert_ports_released, eventually


def test_all_services_start_and_stop(harness: Harness) -> None:
    from scripts.dev.runtime import stop_all

    selected = [harness.api(name) for name in ("platform", "property", "client", "webhook")]
    selected.append(harness.worker())
    selected.append(harness.admin())
    batch, coordinator = harness.start(selected)
    harness.ready(batch)
    state = harness.registry.read_batch(batch)
    assert all(value["ready"] for value in state["services"].values())
    assert "支付任务处理器已注册" in state["services"]["worker"]["reason"]
    assert stop_all(harness.registry, harness.timing) == 0
    coordinator.wait(timeout=5)
    assert_ports_released(selected)
    assert stop_all(harness.registry, harness.timing) == 0
    next_batch, _ = harness.start([selected[0]])
    harness.ready(next_batch)


@pytest.mark.parametrize("name", ["platform", "property", "client", "webhook", "worker"])
def test_individual_services_share_the_lifecycle(harness: Harness, name: str) -> None:
    selected = [harness.worker() if name == "worker" else harness.api(name)]
    batch, coordinator = harness.start(selected)
    harness.ready(batch)
    harness.registry.request_stop(batch)
    assert coordinator.wait(timeout=5) == 0
    assert_ports_released(selected)


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


def test_service_mapping_ports_umi_and_readiness_identity(harness: Harness) -> None:
    from scripts.dev.services import http_probe, services

    definitions = services(ROOT, ["all"])
    assert [service.name for service in definitions] == [
        "platform",
        "property",
        "client",
        "webhook",
        "worker",
        "admin",
    ]
    assert [service.port for service in definitions] == [8001, 8002, 8003, 8004, None, 5173]
    assert definitions[2].command[-2:] == ["backend_app.runtimes.client_api:app", "8003"]
    assert definitions[2].expected_service == "client-api"
    assert definitions[-1].command[1].endswith("apps/admin-web/scripts/dev.cjs")
    assert len(definitions[-1].command) == 2
    selected = [harness.api()]
    batch, _ = harness.start(selected)
    harness.ready(batch)
    wrong = type(selected[0])(**{**asdict(selected[0]), "expected_service": "wrong-service"})
    assert not http_probe(wrong, 1)["ok"]
