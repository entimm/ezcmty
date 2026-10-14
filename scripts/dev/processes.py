"""Repository-scoped ownership and safe process lifecycle primitives."""

from __future__ import annotations

import copy
import ctypes
import fcntl
import json
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

SOURCE_ROOT = Path(__file__).resolve().parents[2]


class DevError(Exception):
    """An actionable failure that is safe to display without configuration secrets."""


@dataclass(frozen=True)
class Identity:
    pid: int
    pgid: int
    started: int

    @classmethod
    def load(cls, value: dict[str, Any]) -> Identity:
        return cls(pid=int(value["pid"]), pgid=int(value["pgid"]), started=int(value["started"]))


class BsdInfo(ctypes.Structure):
    # Darwin's PROC_PIDTBSDINFO, including microsecond start time (not ps lstart).
    _fields_ = (
        [
            (name, ctypes.c_uint32)
            for name in (
                "flags",
                "status",
                "xstatus",
                "pid",
                "ppid",
                "uid",
                "gid",
                "ruid",
                "rgid",
                "svuid",
                "svgid",
                "reserved",
            )
        ]
        + [("comm", ctypes.c_char * 16), ("name", ctypes.c_char * 32)]
        + [
            (name, ctypes.c_uint32)
            for name in (
                "nfiles",
                "pgid",
                "jobc",
                "tdev",
                "tpgid",
            )
        ]
        + [
            ("nice", ctypes.c_int32),
            ("start_sec", ctypes.c_uint64),
            ("start_usec", ctypes.c_uint64),
        ]
    )


def darwin_library() -> ctypes.CDLL:
    library = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
    library.proc_pidinfo.argtypes = [
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_uint64,
        ctypes.c_void_p,
        ctypes.c_int,
    ]
    library.proc_pidinfo.restype = ctypes.c_int
    library.proc_listallpids.argtypes = [ctypes.c_void_p, ctypes.c_int]
    library.proc_listallpids.restype = ctypes.c_int
    return library


LIBPROC = darwin_library() if sys.platform == "darwin" else None


def identity(pid: int, *, include_zombies: bool = False) -> Identity | None:
    if pid <= 0:
        return None
    if LIBPROC is not None:
        info = BsdInfo()
        size = LIBPROC.proc_pidinfo(pid, 3, 0, ctypes.byref(info), ctypes.sizeof(info))
        if size != ctypes.sizeof(info) or info.uid != os.getuid():
            return None
        if info.status == 5 and not include_zombies:
            return None
        return Identity(pid, info.pgid, info.start_sec * 1_000_000 + info.start_usec)
    if sys.platform.startswith("linux"):
        try:
            path = Path(f"/proc/{pid}/stat")
            if path.stat().st_uid != os.getuid():
                return None
            fields = path.read_text().rsplit(")", 1)[1].split()
            if fields[0] == "Z" and not include_zombies:
                return None
            return Identity(pid, int(fields[2]), int(fields[19]))
        except OSError, ValueError, IndexError:
            return None
    raise DevError("开发进程管理支持 macOS 和 Linux；当前系统不支持安全的进程身份验证。")


def is_alive(value: dict[str, Any] | Identity | None) -> bool:
    if value is None:
        return False
    expected = value if isinstance(value, Identity) else Identity.load(value)
    return identity(expected.pid) == expected


def signal_owned(value: dict[str, Any] | Identity, sig: int) -> None:
    expected = value if isinstance(value, Identity) else Identity.load(value)
    if is_alive(expected):
        try:
            os.kill(expected.pid, sig)
        except ProcessLookupError:
            pass


def process_snapshot() -> list[Identity]:
    if LIBPROC is not None:
        count = LIBPROC.proc_listallpids(None, 0) + 256
        buffer = (ctypes.c_int * count)()
        size = LIBPROC.proc_listallpids(buffer, ctypes.sizeof(buffer))
        pids = list(buffer[: max(0, min(size, count))])
    elif sys.platform.startswith("linux"):
        pids = [int(path.name) for path in Path("/proc").iterdir() if path.name.isdigit()]
    else:
        raise DevError("当前系统不支持进程身份验证。")
    return [value for pid in pids if (value := identity(pid)) is not None]


def group_members(group: dict[str, Any], snapshot: list[Identity]) -> list[Identity]:
    root = Identity.load(group["root"])
    known = [root, *(Identity.load(item) for item in group["members"])]
    # A dedicated session cannot be joined by processes from an unrelated session.
    # Require a live recorded member before trusting the numeric process group.
    if (
        not any(item in snapshot for item in known)
        and identity(root.pid, include_zombies=True) != root
    ):
        return []
    return [item for item in snapshot if item.pgid == root.pgid and item.started >= root.started]


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
                        "version": 1,
                        "root": str(self.root),
                        "stopping": None,
                        "batches": {},
                    }
                )
                if state["version"] != 1 or state["root"] != str(self.root):
                    raise ValueError("registry identity")
                if not isinstance(state["batches"], dict):
                    raise ValueError("batches")
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
