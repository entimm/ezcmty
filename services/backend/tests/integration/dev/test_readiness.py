from __future__ import annotations

import sys
import time
from dataclasses import replace

import pytest
from tests.support.dev import HELPER, Harness, assert_ports_released, eventually


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


@pytest.mark.parametrize("background", [False, True], ids=["foreground", "background"])
def test_launcher_timeout_identifies_unready_worker(harness: Harness, background: bool) -> None:
    from scripts.dev.services import Service

    harness.timing = replace(harness.timing, startup=2)
    worker = Service(
        "worker",
        [sys.executable, str(HELPER), "exit", "30", "0"],
        str(harness.registry.root),
        worker=True,
    )
    client = harness.client([worker], background=background)
    output, _ = client.communicate(timeout=10)

    assert client.returncode != 0
    assert "启动总超时（2 秒）：worker: 等待服务启动" in output.decode()
