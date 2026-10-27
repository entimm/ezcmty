"""Repository-scoped ownership and safe process lifecycle primitives."""

from __future__ import annotations

import copy
import fcntl
import json
import math
import os
import signal
import subprocess
import sys
import time
from collections.abc import Generator, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, BinaryIO

import psutil

SOURCE_ROOT = Path(__file__).resolve().parents[2]
IDENTITY_FORMAT = (
    f"psutil-{psutil.__version__}:{sys.implementation.name}-{sys.version.split()[0]}:"
    f"hash-{sys.hash_info.width}"
)


class DevError(Exception):
    """An actionable failure that is safe to display without configuration secrets."""


@dataclass(frozen=True)
class Identity:
    pid: int
    pgid: int
    process_hash: int

    @classmethod
    def load(cls, value: dict[str, Any]) -> Identity:
        pid, pgid, process_hash = (value[key] for key in ("pid", "pgid", "process_hash"))
        if (
            type(pid) is not int
            or pid <= 0
            or type(pgid) is not int
            or pgid <= 0
            or type(process_hash) is not int
        ):
            raise ValueError("Invalid process identity")
        return cls(pid, pgid, process_hash)


def _process_hash(process: psutil.Process, *, include_zombies: bool = False) -> int | None:
    if sys.platform != "darwin" and not sys.platform.startswith("linux"):
        raise DevError("开发进程管理支持 macOS 和 Linux；当前系统不支持安全的进程身份验证。")
    users = process.uids()
    if users.real != os.getuid() or users.effective != os.getuid():
        return None
    if process.status() == psutil.STATUS_ZOMBIE and not include_zombies:
        return None
    created = process.create_time()
    if not math.isfinite(created) or created <= 0:
        return None
    # psutil 7.2 uses a monotonic creation identity for hashing on macOS/Linux;
    # public create_time() is wall-clock based and must not be persisted as identity.
    fingerprint = hash(process)
    return fingerprint if process.is_running() else None


def _identity(process: psutil.Process, *, include_zombies: bool = False) -> Identity | None:
    fingerprint = _process_hash(process, include_zombies=include_zombies)
    if fingerprint is None:
        return None
    owner = Identity(process.pid, os.getpgid(process.pid), fingerprint)
    return owner if process.is_running() else None


def identity(pid: int, *, include_zombies: bool = False) -> Identity | None:
    if pid <= 0:
        return None
    try:
        return _identity(psutil.Process(pid), include_zombies=include_zombies)
    except psutil.Error, OSError:
        return None


def is_alive(value: dict[str, Any] | Identity | None) -> bool:
    if value is None:
        return False
    expected = value if isinstance(value, Identity) else Identity.load(value)
    return identity(expected.pid) == expected


def signal_owned(value: dict[str, Any] | Identity, sig: int) -> None:
    expected = value if isinstance(value, Identity) else Identity.load(value)
    try:
        process = psutil.Process(expected.pid)
        if _identity(process) == expected:
            # Keep the checked handle so send_signal() also detects subsequent PID reuse.
            process.send_signal(sig)
    except psutil.Error, OSError:
        pass


def process_snapshot() -> list[Identity]:
    # Use fresh handles instead of process_iter()'s cached Process identities.
    return [value for pid in psutil.pids() if (value := identity(pid)) is not None]


def _zombie_root(root: Identity) -> bool:
    # macOS cannot getpgid() a zombie. A recorded group leader's PID/hash still
    # verifies that its original group has not been recycled while it is unreaped.
    try:
        process = psutil.Process(root.pid)
        return (
            process.status() == psutil.STATUS_ZOMBIE
            and _process_hash(process, include_zombies=True) == root.process_hash
        )
    except psutil.Error, OSError:
        return False


def group_members(group: dict[str, Any], snapshot: list[Identity]) -> list[Identity]:
    root = Identity.load(group["root"])
    if root.pid != root.pgid:
        return []
    known = [root, *(Identity.load(item) for item in group["members"])]
    # A dedicated session cannot be joined by processes from an unrelated session.
    # Require a live recorded member before trusting the numeric process group.
    if not any(item in snapshot for item in known) and not _zombie_root(root):
        return []
    return [item for item in snapshot if item.pgid == root.pgid]


def atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


class Registry:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.directory = self.root / ".dev" / "run"
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)

    def batch_directory(self, batch_id: str) -> Path:
        if not batch_id or any(character not in "0123456789abcdef" for character in batch_id):
            raise DevError("无效的启动批次标识。")
        return self.directory / batch_id

    @contextmanager
    def locked(self) -> Generator[dict[str, Any]]:
        with (self.directory / "lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            path = self.directory / "state.json"
            try:
                state: dict[str, Any] = (
                    json.loads(path.read_text())
                    if path.exists()
                    else {
                        "version": 2,
                        "identity_format": IDENTITY_FORMAT,
                        "root": str(self.root),
                        "stopping": None,
                        "batches": {},
                    }
                )
                if state["version"] not in {1, 2} or state["root"] != str(self.root):
                    raise ValueError("registry identity")
                if not isinstance(state["batches"], dict):
                    raise ValueError("batches")
                if state["version"] == 1 or state.get("identity_format") != IDENTITY_FORMAT:
                    if state["batches"] or state["stopping"] is not None:
                        raise DevError(
                            "开发进程登记格式与当前工具不兼容；请先使用升级前版本执行 make stop，"
                            "保留现有进程与登记。"
                        )
                    state.update(version=2, identity_format=IDENTITY_FORMAT)
                for batch_id, batch in state["batches"].items():
                    self.batch_directory(batch_id)
                    if not isinstance(batch["requested"], list):
                        raise ValueError("requested")
                    if batch["coordinator"] is not None:
                        Identity.load(batch["coordinator"])
                    for group in batch["processes"].values():
                        Identity.load(group["root"])
                        for member in group["members"]:
                            Identity.load(member)
                if state["stopping"] is not None:
                    Identity.load(state["stopping"])
            except (OSError, ValueError, TypeError, KeyError) as exc:
                raise DevError(
                    "运行状态无法安全读取；保留进程，请检查 .dev/run/state.json。"
                ) from exc
            yield state
            atomic_json(path, state)
            for batch_id, batch in state["batches"].items():
                atomic_json(self.batch_directory(batch_id) / "state.json", batch)

    def read_batch(self, batch_id: str) -> dict[str, Any]:
        with self.locked() as state:
            if batch_id in state["batches"]:
                result: dict[str, Any] = copy.deepcopy(state["batches"][batch_id])
                return result
        result = json.loads((self.batch_directory(batch_id) / "state.json").read_text())
        return result

    def refresh(self, state: dict[str, Any]) -> None:
        snapshot = process_snapshot()
        for batch in state["batches"].values():
            for group in batch["processes"].values():
                group["members"] = [asdict(item) for item in group_members(group, snapshot)]
        if state["stopping"] is not None and not is_alive(state["stopping"]):
            state["stopping"] = None
        for batch_id, batch in list(state["batches"].items()):
            if is_alive(batch["coordinator"]) or any(
                group["members"] for group in batch["processes"].values()
            ):
                continue
            batch.update(status="failed", reason="协调进程已退出，已清理过期登记。")
            atomic_json(self.batch_directory(batch_id) / "state.json", batch)
            del state["batches"][batch_id]

    def spawn(
        self,
        batch_id: str,
        name: str,
        command: Sequence[str],
        cwd: Path,
        *,
        output: BinaryIO | int,
        environment: dict[str, str] | None = None,
    ) -> subprocess.Popen[bytes]:
        with self.locked() as state:
            return self.spawn_locked(
                state, batch_id, name, command, cwd, output=output, environment=environment
            )

    def spawn_locked(
        self,
        state: dict[str, Any],
        batch_id: str,
        name: str,
        command: Sequence[str],
        cwd: Path,
        *,
        output: BinaryIO | int,
        coordinator: bool = False,
        environment: dict[str, str] | None = None,
    ) -> subprocess.Popen[bytes]:
        batch = state["batches"].get(batch_id)
        if batch is None or batch["status"] == "stopping" or state["stopping"] is not None:
            raise DevError("批次正在停止，取消继续启动服务。")
        process = spawn_gated(command, cwd, output, environment)
        child = identity(process.pid)
        if child is None:
            process.gate.close()
            process.wait(timeout=5)
            raise DevError(f"{name}：进程未能建立可验证的身份。")
        try:
            if coordinator:
                batch["coordinator"] = asdict(child)
            else:
                batch["processes"][name] = {"root": asdict(child), "members": [asdict(child)]}
            # Persist before releasing the gate, even if this launcher dies immediately after.
            atomic_json(self.directory / "state.json", state)
            atomic_json(self.batch_directory(batch_id) / "state.json", batch)
            process.gate.write(b"G")
            process.gate.close()
        except BaseException:
            process.gate.close()
            signal_owned(child, signal.SIGKILL)
            process.wait(timeout=5)
            raise
        return process

    def request_stop(self, batch_id: str, *, failure: str = "") -> None:
        with self.locked() as state:
            batch = state["batches"].get(batch_id)
            if batch is not None:
                batch["status"] = "stopping"
                if failure:
                    batch["abort_reason"] = failure
                if batch["coordinator"] is not None:
                    signal_owned(batch["coordinator"], signal.SIGTERM)

    def finish(self, batch_id: str, status: str, reason: str) -> None:
        with self.locked() as state:
            batch = state["batches"].get(batch_id)
            if batch is not None:
                batch.update(status=status, reason=reason)
                atomic_json(self.batch_directory(batch_id) / "state.json", batch)
                del state["batches"][batch_id]


class GatedProcess(subprocess.Popen[bytes]):
    gate: BinaryIO


def subprocess_environment() -> dict[str, str]:
    environment = dict(os.environ)
    environment["PYTHONUNBUFFERED"] = "1"
    environment["PYTHONPATH"] = os.pathsep.join(
        filter(
            None,
            (
                str(SOURCE_ROOT),
                environment.get("PYTHONPATH", ""),
            ),
        )
    )
    return environment


def spawn_gated(
    command: Sequence[str],
    cwd: Path,
    output: BinaryIO | int,
    environment: dict[str, str] | None = None,
) -> GatedProcess:
    read_fd, write_fd = os.pipe()
    try:
        process = GatedProcess(
            [
                sys.executable,
                "-m",
                "scripts.dev.processes",
                str(read_fd),
                json.dumps(list(command)),
            ],
            cwd=cwd,
            env={**subprocess_environment(), **(environment or {})},
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            pass_fds=(read_fd,),
        )
    except BaseException:
        os.close(write_fd)
        raise
    finally:
        os.close(read_fd)
    process.gate = os.fdopen(write_fd, "wb", buffering=0)
    return process


def terminate_batch(registry: Registry, batch_id: str, graceful: float, forced: float) -> bool:
    """Stop services first, preserving identities for orphan recovery by make stop."""
    deadline = time.monotonic() + graceful
    sent: set[Identity] = set()
    while True:
        with registry.locked() as state:
            batch = state["batches"].get(batch_id)
            if batch is None:
                return True
            snapshot = process_snapshot()
            members: list[Identity] = []
            for group in batch["processes"].values():
                current = group_members(group, snapshot)
                group["members"] = [asdict(item) for item in current]
                members.extend(current)
                root = Identity.load(group["root"])
                # Let supervisors perform their own normal child shutdown first.
                targets = [root] if root in current else current
                for target in targets:
                    if target not in sent:
                        signal_owned(target, signal.SIGTERM)
                        sent.add(target)
            if not members:
                return True
        if time.monotonic() >= deadline:
            break
        time.sleep(0.1)
    deadline = time.monotonic() + forced
    while True:
        with registry.locked() as state:
            batch = state["batches"].get(batch_id)
            if batch is None:
                return True
            snapshot = process_snapshot()
            members = []
            for group in batch["processes"].values():
                current = group_members(group, snapshot)
                group["members"] = [asdict(item) for item in current]
                members.extend(current)
                for member in current:
                    signal_owned(member, signal.SIGKILL)
            if not members:
                return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.1)


if __name__ == "__main__":
    fd = int(sys.argv[1])
    with os.fdopen(fd, "rb", buffering=0) as gate:
        permitted = gate.read(1) == b"G"
    if permitted:
        arguments = json.loads(sys.argv[2])
        os.execvpe(arguments[0], arguments, os.environ)
