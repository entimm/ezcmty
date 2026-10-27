from __future__ import annotations

import socket
import subprocess
import sys
from dataclasses import asdict

import pytest
from tests.support.dev import HELPER, Harness, assert_ports_released, eventually


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
        stale = {**asdict(actual), "process_hash": actual.process_hash ^ 1}
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
