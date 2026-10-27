from __future__ import annotations

import json
import os
import signal
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock, Mock

import psutil
import pytest
from pytest import MonkeyPatch
from scripts.dev import processes


@pytest.fixture
def process(monkeypatch: MonkeyPatch) -> MagicMock:
    child = MagicMock(spec=psutil.Process)
    child.pid = 123
    cast(Mock, child.__hash__).return_value = 42
    child.uids.return_value = SimpleNamespace(real=1000, effective=1000)
    child.create_time.return_value = 1234.5
    child.status.return_value = psutil.STATUS_RUNNING
    child.is_running.return_value = True
    monkeypatch.setattr(os, "getuid", lambda: 1000)
    monkeypatch.setattr(os, "getpgid", lambda pid: 123)
    monkeypatch.setattr(psutil, "Process", Mock(return_value=child))
    return child


@pytest.mark.parametrize("fingerprint", [0, -42, 42])
def test_identity_round_trip_preserves_signed_fingerprint(fingerprint: int) -> None:
    expected = processes.Identity(123, 123, fingerprint)

    assert processes.Identity.load(asdict(expected)) == expected


@pytest.mark.parametrize(
    ("field", "value"),
    [
        pytest.param("pid", True, id="boolean-pid"),
        pytest.param("pid", "123", id="string-pid"),
        pytest.param("pid", 0, id="zero-pid"),
        pytest.param("pid", -1, id="negative-pid"),
        pytest.param("pgid", False, id="boolean-group"),
        pytest.param("pgid", 0, id="zero-group"),
        pytest.param("process_hash", True, id="boolean-fingerprint"),
        pytest.param("process_hash", "42", id="string-fingerprint"),
        pytest.param("process_hash", 42.5, id="fractional-fingerprint"),
    ],
)
def test_identity_load_rejects_unverifiable_metadata(field: str, value: object) -> None:
    metadata = {"pid": 123, "pgid": 123, "process_hash": 42, field: value}

    with pytest.raises(ValueError):
        processes.Identity.load(metadata)


def test_identity_uses_stable_fingerprint_when_wall_clock_changes(process: MagicMock) -> None:
    before = processes.identity(process.pid)
    process.create_time.return_value += 3600

    assert before == processes.Identity(123, 123, 42)
    assert before is not None
    assert processes.identity(process.pid) == before
    assert processes.is_alive(asdict(before))


@pytest.mark.parametrize("uid_field", ["real", "effective"])
def test_foreign_user_identity_is_excluded(process: MagicMock, uid_field: str) -> None:
    setattr(process.uids.return_value, uid_field, 2000)

    assert processes.identity(process.pid) is None


@pytest.mark.parametrize("created", [0.0, -1.0, float("inf"), float("nan")])
def test_missing_or_invalid_creation_time_is_not_an_identity(
    process: MagicMock, created: float
) -> None:
    process.create_time.return_value = created

    assert processes.identity(process.pid) is None


def test_reused_pid_is_not_reported_as_alive(process: MagicMock) -> None:
    process.is_running.return_value = False

    assert processes.identity(process.pid) is None


def test_zombie_identity_requires_explicit_opt_in_when_group_is_available(
    process: MagicMock,
) -> None:
    process.status.return_value = psutil.STATUS_ZOMBIE

    assert processes.identity(process.pid) is None
    assert processes.identity(process.pid, include_zombies=True) == processes.Identity(123, 123, 42)


def test_zombie_root_keeps_group_ownership_when_os_cannot_read_its_group(
    monkeypatch: MonkeyPatch, process: MagicMock
) -> None:
    process.status.return_value = psutil.STATUS_ZOMBIE
    monkeypatch.setattr(os, "getpgid", Mock(side_effect=ProcessLookupError))
    root = processes.Identity(123, 123, 42)
    child = processes.Identity(124, 123, 43)
    external = processes.Identity(125, 125, 44)
    group = {"root": asdict(root), "members": [asdict(root)]}

    assert processes.identity(root.pid, include_zombies=True) is None
    assert processes.group_members(group, [child, external]) == [child]


@pytest.mark.parametrize(
    "error",
    [psutil.AccessDenied(123), psutil.NoSuchProcess(123), OSError("process disappeared")],
    ids=["access-denied", "exited", "os-error"],
)
def test_unreadable_process_is_not_trusted(process: MagicMock, error: Exception) -> None:
    process.uids.side_effect = error

    assert processes.identity(process.pid) is None


@pytest.mark.parametrize("pid", [0, -1])
def test_nonpositive_pid_cannot_be_signalled(process: MagicMock, pid: int) -> None:
    assert processes.identity(pid) is None
    process.send_signal.assert_not_called()


def test_snapshot_does_not_keep_a_previous_incarnation_of_a_pid(
    monkeypatch: MonkeyPatch, process: MagicMock
) -> None:
    monkeypatch.setattr(psutil, "pids", lambda: [123])
    replacement = MagicMock()
    replacement.pid = process.pid
    replacement.uids.return_value = process.uids.return_value
    replacement.create_time.return_value = process.create_time.return_value
    replacement.status.return_value = psutil.STATUS_RUNNING
    replacement.is_running.return_value = True
    cast(Mock, replacement.__hash__).return_value = 43
    cast(Mock, psutil.Process).side_effect = [process, replacement]

    assert processes.process_snapshot() == [processes.Identity(123, 123, 42)]
    assert processes.process_snapshot() == [processes.Identity(123, 123, 43)]


def test_signal_uses_the_process_that_passed_ownership_checks(process: MagicMock) -> None:
    processes.signal_owned(processes.Identity(123, 123, 42), signal.SIGTERM)

    cast(Mock, psutil.Process).assert_called_once_with(123)
    process.send_signal.assert_called_once_with(signal.SIGTERM)


@pytest.mark.parametrize(
    "expected", [processes.Identity(123, 123, 41), processes.Identity(123, 124, 42)]
)
def test_stale_identity_does_not_signal_current_process(
    process: MagicMock, expected: processes.Identity
) -> None:
    processes.signal_owned(asdict(expected), signal.SIGKILL)

    process.send_signal.assert_not_called()


def test_pid_reuse_during_signal_is_tolerated_without_retry(process: MagicMock) -> None:
    process.send_signal.side_effect = psutil.NoSuchProcess(123)

    processes.signal_owned(processes.Identity(123, 123, 42), signal.SIGTERM)

    process.send_signal.assert_called_once_with(signal.SIGTERM)


@pytest.mark.parametrize("anchor", ["root", "member", "zombie", "none", "reused", "shared"])
def test_group_discovery_requires_a_verifiable_independent_group(
    process: MagicMock, anchor: str
) -> None:
    root = processes.Identity(10, 99 if anchor == "shared" else 10, 1)
    member = processes.Identity(11, root.pgid, 2)
    child = processes.Identity(12, root.pgid, 3)
    external = processes.Identity(13, 13, 4)
    snapshot = [child, external]
    if anchor in {"root", "shared"}:
        snapshot.append(root)
    elif anchor == "member":
        snapshot.append(member)
    elif anchor == "reused":
        snapshot.append(processes.Identity(root.pid, root.pgid, 99))
    process.pid = root.pid
    cast(Mock, process.__hash__).return_value = root.process_hash if anchor == "zombie" else 99
    process.status.return_value = (
        psutil.STATUS_ZOMBIE if anchor in {"zombie", "reused"} else psutil.STATUS_RUNNING
    )
    group = {"root": asdict(root), "members": [asdict(member)]}

    actual = processes.group_members(group, snapshot)

    if anchor in {"root", "member", "zombie"}:
        assert child in actual
        assert external not in actual
        assert all(item.pgid == root.pgid for item in actual)
    else:
        assert actual == []


@pytest.mark.parametrize("version", [1, 2], ids=["legacy-empty", "different-format-empty"])
def test_empty_registry_upgrades_to_current_identity_format(tmp_path: Path, version: int) -> None:
    registry = processes.Registry(tmp_path)
    state_path = registry.directory / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "version": version,
                "identity_format": "older-format",
                "root": str(tmp_path.resolve()),
                "batches": {},
                "stopping": None,
            }
        )
    )

    with registry.locked() as state:
        assert state["version"] == 2
        assert state["identity_format"] == processes.IDENTITY_FORMAT

    saved = json.loads(state_path.read_text())
    assert saved["version"] == 2
    assert saved["identity_format"] == processes.IDENTITY_FORMAT


@pytest.mark.parametrize("version", [1, 2], ids=["legacy-active", "different-format-active"])
@pytest.mark.parametrize("active", ["batch", "stopper"])
def test_incompatible_active_registry_is_preserved(
    tmp_path: Path, version: int, active: str
) -> None:
    registry = processes.Registry(tmp_path)
    state_path = registry.directory / "state.json"
    saved = json.dumps(
        {
            "version": version,
            "identity_format": "older-format",
            "root": str(tmp_path.resolve()),
            "batches": {"a" * 32: {}} if active == "batch" else {},
            "stopping": {"pid": 123, "pgid": 123, "started": 1} if active == "stopper" else None,
        }
    )
    state_path.write_text(saved)

    with pytest.raises(processes.DevError, match="升级前版本" if version == 1 else None):
        with registry.locked():
            pytest.fail("incompatible process ownership must not be accepted")

    assert state_path.read_text() == saved
