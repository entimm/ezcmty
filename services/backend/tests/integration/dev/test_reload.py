from __future__ import annotations

import signal

from tests.support.dev import Harness, assert_ports_released, eventually


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
