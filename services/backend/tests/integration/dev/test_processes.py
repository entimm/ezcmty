from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

import psutil
import pytest
from scripts.dev.processes import (
    Identity,
    group_members,
    identity,
    is_alive,
    process_snapshot,
    signal_owned,
    spawn_gated,
    subprocess_environment,
)
from tests.support.dev import eventually


@pytest.mark.parametrize("hash_seed", ["1", "2", "random"])
def test_identity_matches_in_another_interpreter(hash_seed: str) -> None:
    owner = identity(os.getpid())
    assert owner is not None
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import json, sys; from dataclasses import asdict; "
            "from scripts.dev.processes import identity; "
            "print(json.dumps(asdict(identity(int(sys.argv[1])))))",
            str(owner.pid),
        ],
        env={**subprocess_environment(), "PYTHONHASHSEED": hash_seed},
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    assert Identity.load(json.loads(result.stdout)) == owner


def test_zombie_leader_and_known_orphan_preserve_group_ownership(tmp_path: Path) -> None:
    child_file = tmp_path / "child.pid"
    command = [
        sys.executable,
        "-c",
        "import os, signal, sys; from pathlib import Path\n"
        "child = os.fork()\n"
        "if child:\n"
        "    Path(sys.argv[1]).write_text(str(child))\n"
        "else:\n"
        "    signal.alarm(30)\n"
        "    while True: signal.pause()\n",
        str(child_file),
    ]
    root = spawn_gated(command, tmp_path, subprocess.DEVNULL)
    child: Identity | None = None
    try:
        owner = identity(root.pid)
        assert owner is not None and owner.pid == owner.pgid
        root.gate.write(b"G")
        root.gate.close()
        eventually(lambda: child_file.is_file() and bool(child_file.read_text()))
        child = identity(int(child_file.read_text()))
        assert child is not None
        eventually(lambda: psutil.Process(root.pid).status() == psutil.STATUS_ZOMBIE)
        assert identity(root.pid) is None
        group = {"root": asdict(owner), "members": [asdict(owner)]}
        members = group_members(group, process_snapshot())
        assert child in members and owner not in members

        group["members"] = [asdict(member) for member in members]
        assert root.wait(timeout=5) == 0
        assert child in group_members(group, process_snapshot())
        signal_owned(child, signal.SIGTERM)
        eventually(lambda: not is_alive(child))
    finally:
        root.gate.close()
        if child is not None:
            signal_owned(child, signal.SIGKILL)
            eventually(lambda: not is_alive(child))
        if root.poll() is None:
            root.kill()
        root.wait(timeout=5)
