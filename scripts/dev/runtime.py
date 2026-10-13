"""One coordinator per batch, shared by foreground and detached launches."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from scripts.dev.processes import (
    DevError,
    Identity,
    Registry,
    atomic_json,
    group_members,
    identity,
    is_alive,
    process_snapshot,
    signal_owned,
    terminate_batch,
)
from scripts.dev.services import DEFAULT_TIMING, Service, Timing, check_ports, probe_command


def announce(message: str) -> None:
    print(f"[开发] {message}", flush=True)


class LogTail:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.offset = 0
        self.partial = b""

    def lines(self) -> list[str]:
        try:
            with self.path.open("rb") as stream:
                stream.seek(self.offset)
                content = stream.read(262_144)
                self.offset = stream.tell()
        except FileNotFoundError:
            return []
        lines = (self.partial + content).split(b"\n")
        self.partial = lines.pop()
        return [line.decode("utf-8", errors="replace").rstrip("\r") for line in lines]


@dataclass
class Probe:
    process: subprocess.Popen[bytes]
    deadline: float
    owner: Identity
    generation: int = 0

    @classmethod
    def start(
        cls,
        registry: Registry,
        batch_id: str,
        name: str,
        command: list[str],
        cwd: Path,
        timing: Timing,
        generation: int = 0,
    ) -> Probe:
        process = registry.spawn(batch_id, f"probe-{name}", command, cwd, output=subprocess.PIPE)
        owner = identity(process.pid)
        if owner is None:
            raise DevError(f"{name}：就绪探测进程未能启动。")
        return cls(process, time.monotonic() + timing.probe, owner, generation)

    def result(self, now: float) -> dict[str, Any] | None:
        if self.process.poll() is None:
            if now < self.deadline:
                return None
            signal_owned(self.owner, signal.SIGKILL)
            self.process.wait(timeout=5)
            if self.process.stdout is not None:
                self.process.stdout.close()
            return {"ok": False, "reason": "单次就绪探测超时"}
        assert self.process.stdout is not None
        with self.process.stdout as output:
            content = output.read(65_537)
        try:
            result: dict[str, Any] = json.loads(content.splitlines()[-1])
            if self.process.returncode != 0 or not isinstance(result.get("ok"), bool):
                raise ValueError("probe failed")
            if result.get("finished", self.deadline) > self.deadline:
                return {"ok": False, "reason": "单次就绪探测超时"}
            return result
        except (ValueError, IndexError, AttributeError):
            return {"ok": False, "reason": f"就绪探测进程退出（{self.process.returncode}）"}


@dataclass
class RunningService:
    service: Service
    process: subprocess.Popen[bytes]
    events: Path
    log: LogTail
    ready: bool = False
    generation: int = -1
    child: dict[str, Any] | None = None
    phase: str = "starting"
    recovery_deadline: float | None = None
    probe: Probe | None = None
    next_probe: float = 0
    reason: str = "等待服务启动"

    def observe(self, timing: Timing) -> None:
        if self.service.expected_service is not None:
            try:
                event: dict[str, Any] = json.loads(self.events.read_text())
            except FileNotFoundError:
                event = {}
            if event.get("phase") == "failed":
                raise DevError(f"{self.service.name}：{event['reason']}")
            if event:
                generation = int(event["generation"])
                if generation != self.generation:
                    self.generation = generation
                    self.ready = False
                    self.reason = "等待热重载后就绪" if generation else "等待 API 就绪"
                    if event["reload_started"] is not None and self.recovery_deadline is None:
                        self.recovery_deadline = float(event["reload_started"]) + timing.reload
                    if generation:
                        announce(
                            f"{self.service.name} 热重载中，最多等待 {timing.reload:g} 秒恢复。"
                        )
                self.child = event["child"]
                self.phase = event["phase"]
                if self.phase == "started" and not is_alive(self.child):
                    # The reloader publishes its intent before terminating the old child.
                    # Re-read after the liveness check to avoid mistaking that race for a crash.
                    latest = json.loads(self.events.read_text())
                    if latest == event:
                        raise DevError(f"{self.service.name}：实际 API 子进程意外退出。")
                    self.phase = "reloading"
        if self.process.poll() is not None:
            raise DevError(
                f"{self.service.name}：服务进程意外退出（退出码 {self.process.returncode}）。"
            )
        if self.service.worker and not self.ready:
            for line in self.log.lines():
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if (
                    isinstance(record, dict)
                    and record.get("service") == "worker"
                    and record.get("message") == "worker_started task_handlers=0"
                ):
                    self.ready = True
                    self.phase = "ready"
                    self.reason = "占位 Worker 已启动（task_handlers=0）"
                    announce(f"{self.service.name}：{self.reason}")

    def check_readiness(
        self,
        registry: Registry,
        batch_id: str,
        timing: Timing,
        now: float,
    ) -> None:
        if self.recovery_deadline is not None and now >= self.recovery_deadline:
            raise DevError(
                f"{self.service.name}：热重载后 {timing.reload:g} 秒内未恢复就绪；{self.reason}。"
            )
        if self.probe is not None:
            result = self.probe.result(now)
            if result is None:
                return
            generation = self.probe.generation
            self.probe = None
            self.next_probe = now + timing.interval
            if generation != self.generation or self.phase == "reloading":
                return
            self.reason = str(result["reason"])
            if result["ok"]:
                self.ready = True
                self.phase = "ready"
                self.recovery_deadline = None
                if self.service.expected_service is not None:
                    atomic_json(
                        self.events.with_suffix(".ack.json"), {"generation": self.generation}
                    )
                announce(f"{self.service.name} 已就绪：{self.service.url}")
        if self.ready or self.service.worker or self.phase == "reloading" or now < self.next_probe:
            return
        if self.service.expected_service is not None and self.generation < 0:
            return
        self.probe = Probe.start(
            registry,
            batch_id,
            self.service.name,
            probe_command(self.service, timing),
            Path(self.service.cwd),
            timing,
            self.generation,
        )

    def state(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "phase": self.phase,
            "generation": self.generation,
            "child": self.child,
            "reason": self.reason,
        }


def launch(
    registry: Registry,
    selected: list[Service],
    background: bool,
    *,
    preflight: list[str] | None = None,
    preflight_cwd: Path | None = None,
    timing: Timing = DEFAULT_TIMING,
) -> tuple[str, subprocess.Popen[bytes]]:
    batch_id = uuid.uuid4().hex
    with registry.locked() as state:
        registry.refresh(state)
        if state["stopping"] is not None:
            raise DevError("本仓库正在执行 make stop；请等待停止完成后重试。")
        requested = {service.name for service in selected}
        conflicts = []
        for key, batch in state["batches"].items():
            overlap = requested.intersection(batch["requested"])
            if overlap:
                coordinator_pid = batch["coordinator"]["pid"] if batch["coordinator"] else "已退出"
                conflicts.append(
                    f"批次 {key}（{batch['status']}），服务 {', '.join(sorted(overlap))}，"
                    f"协调器 PID {coordinator_pid}"
                )
        if conflicts:
            raise DevError(
                "启动请求已拒绝，已有实例：\n  "
                + "\n  ".join(conflicts)
                + "\n原实例继续运行；停止方式：make stop。"
            )
        for service in selected:
            if service.name == "admin":
                umi = Path(service.cwd) / "node_modules" / "@umijs" / "max" / "bin" / "max.js"
                if not Path(service.command[1]).is_file() or not umi.is_file():
                    raise DevError("管理后台依赖未安装；请先执行 make install。")
        check_ports(selected)
        directory = registry.batch_directory(batch_id)
        directory.mkdir(mode=0o700)
        atomic_json(
            directory / "request.json",
            {
                "services": [asdict(service) for service in selected],
                "preflight": preflight,
                "preflight_cwd": str(preflight_cwd or registry.root),
                "timing": asdict(timing),
            },
        )
        state["batches"][batch_id] = {
            "id": batch_id,
            "requested": [service.name for service in selected],
            "mode": "background" if background else "foreground",
            "accepted": time.monotonic(),
            "status": "starting",
            "reason": "",
            "coordinator": None,
            "processes": {},
            "services": {},
        }
        try:
            with (directory / "coordinator.log").open("ab", buffering=0) as log:
                process = registry.spawn_locked(
                    state,
                    batch_id,
                    "coordinator",
                    [
                        sys.executable,
                        "-m",
                        "scripts.dev",
                        "_coordinate",
                        str(registry.root),
                        batch_id,
                    ],
                    registry.root,
                    output=log,
                    coordinator=True,
                )
        except BaseException:
            state["batches"].pop(batch_id, None)
            atomic_json(registry.directory / "state.json", state)
            raise
    return batch_id, process


def coordinate(registry: Registry, batch_id: str) -> int:
    directory = registry.batch_directory(batch_id)
    request = json.loads((directory / "request.json").read_text())
    selected = [Service(**value) for value in request["services"]]
    timing = Timing(**request["timing"])
    deadline = float(registry.read_batch(batch_id)["accepted"]) + timing.startup
    stopped = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, lambda *_: stopped.set())
    running: list[RunningService] = []
    children: list[subprocess.Popen[bytes]] = []
    preflight: Probe | None = None
    dependencies_ready = request["preflight"] is None
    next_preflight = 0.0
    reason = "正常停止"
    status = "stopped"
    successful = False
    try:
        announce(f"批次 {batch_id} 启动中；总超时 {timing.startup:g} 秒。")
        while True:
            now = time.monotonic()
            batch = registry.read_batch(batch_id)
            if stopped.is_set() or batch["status"] == "stopping":
                reason = batch.get("abort_reason", "收到停止请求")
                if batch.get("abort_reason"):
                    status = "failed"
                break
            if not successful and now >= deadline:
                details = (
                    "; ".join(
                        f"{item.service.name}: {item.reason}" for item in running if not item.ready
                    )
                    or reason
                )
                raise DevError(f"启动总超时（{timing.startup:g} 秒）：{details}")
            if not dependencies_ready:
                if preflight is None and now >= next_preflight:
                    announce("检查 services/backend/.env 配置及 MySQL、Redis（只读）。")
                    preflight = Probe.start(
                        registry,
                        batch_id,
                        "dependencies",
                        request["preflight"],
                        Path(request["preflight_cwd"]),
                        timing,
                    )
                    children.append(preflight.process)
                if preflight is not None:
                    result = preflight.result(now)
                    if result is not None:
                        preflight = None
                        next_preflight = now + timing.interval
                        reason = str(result["reason"])
                        if result.get("fatal"):
                            raise DevError(reason)
                        dependencies_ready = bool(result["ok"])
                        if (
                            dependencies_ready
                            and any(service.worker for service in selected)
                            and (result.get("log_level", "INFO") not in ("DEBUG", "INFO"))
                        ):
                            raise DevError(
                                "Worker 就绪需要观察 INFO 级 worker_started 标记；"
                                "请将 APP_LOG_LEVEL 设置为 INFO 或 DEBUG。"
                            )
                        if dependencies_ready or reason != batch.get("reason"):
                            announce(reason)
                        with registry.locked() as state:
                            state["batches"][batch_id]["reason"] = reason
            if dependencies_ready and not running:
                check_ports(selected)
                for service in selected:
                    events = directory / f"{service.name}.events.json"
                    with (directory / f"{service.name}.log").open("ab", buffering=0) as log:
                        process = registry.spawn(
                            batch_id,
                            service.name,
                            service.command,
                            Path(service.cwd),
                            output=log,
                            environment={"DEV_API_EVENT_FILE": str(events)},
                        )
                    children.append(process)
                    running.append(
                        RunningService(
                            service,
                            process,
                            events,
                            LogTail(directory / f"{service.name}.log"),
                        )
                    )
            # Capture descendants while exited direct children are still unreaped.
            # A zombie leader retains its precise identity, so orphaned descendants
            # are registered before Popen.poll() can release the leader's PID.
            with registry.locked() as state:
                registry.refresh(state)
            for item in running:
                item.observe(timing)
                before = item.probe
                item.check_readiness(registry, batch_id, timing, now)
                if item.probe is not None and item.probe is not before:
                    children.append(item.probe.process)
            with registry.locked() as state:
                current = state["batches"][batch_id]
                registry.refresh(state)
                current["services"] = {item.service.name: item.state() for item in running}
                if not successful and running and all(item.ready for item in running):
                    if time.monotonic() >= deadline:
                        raise DevError(f"启动总超时（{timing.startup:g} 秒），取消报告就绪。")
                    if current["status"] == "stopping" or state["stopping"] is not None:
                        break
                    current["status"] = "running"
                    current["reason"] = "全部所选服务已就绪"
                    successful = True
                    announce("全部所选服务已就绪。")
            stopped.wait(timing.interval)
    except DevError as exc:
        current = registry.read_batch(batch_id)
        if stopped.is_set() or current["status"] == "stopping":
            reason = current.get("abort_reason", "启动被停止请求取消")
            if current.get("abort_reason"):
                status = "failed"
        else:
            status = "failed"
            reason = str(exc)
            announce(f"失败：{reason}；只清理本批次进程。")
    except Exception as exc:
        # Exception messages can contain credentials. Only the type is safe to display.
        status = "failed"
        reason = f"协调器异常（{type(exc).__name__}）；详情请检查启动配置及日志。"
        announce(reason)
    finally:
        announce("正在停止本批次应用进程及其子进程。")
        with registry.locked() as state:
            if batch_id in state["batches"]:
                state["batches"][batch_id]["status"] = "stopping"
                state["batches"][batch_id]["reason"] = reason
        clean = terminate_batch(registry, batch_id, timing.graceful, timing.forced)
        for child in children:
            if child.poll() is not None:
                child.wait()
                if child.stdout is not None and not child.stdout.closed:
                    child.stdout.close()
        if clean:
            registry.finish(batch_id, status, reason)
            announce(f"本批次进程已全部退出：{reason}。")
        else:
            status = "failed"
            announce("仍有登记进程未退出，保留身份信息；请执行 make stop 重试。")
    return 1 if status == "failed" else 0


def stop_all(registry: Registry, timing: Timing = DEFAULT_TIMING) -> int:
    owner = identity(os.getpid())
    assert owner is not None
    with registry.locked() as state:
        registry.refresh(state)
        already_stopping = state["stopping"] is not None
        if not already_stopping:
            if not state["batches"]:
                announce("没有由本仓库开发入口登记的运行服务。")
                return 0
            state["stopping"] = asdict(owner)
            for batch in state["batches"].values():
                batch["status"] = "stopping"
                if batch["coordinator"] is not None:
                    signal_owned(batch["coordinator"], signal.SIGTERM)
    if already_stopping:
        announce("已有停止请求，等待其完成。")
        while True:
            with registry.locked() as state:
                registry.refresh(state)
                if state["stopping"] is None:
                    break
            time.sleep(0.1)
        return stop_all(registry, timing)
    announce("停止全部登记批次；先正常退出，超时后终止仍存活的所属进程。")
    started = time.monotonic()
    sent: set[Identity] = set()
    try:
        while True:
            now = time.monotonic()
            with registry.locked() as state:
                registry.refresh(state)
                if not state["batches"]:
                    announce("全部登记应用进程已退出，运行登记已清理。")
                    return 0
                snapshot = process_snapshot()
                for batch_id, batch in list(state["batches"].items()):
                    coordinator_alive = is_alive(batch["coordinator"])
                    members = [
                        member
                        for group in batch["processes"].values()
                        for member in group_members(group, snapshot)
                    ]
                    if now - started >= timing.graceful:
                        for member in members:
                            signal_owned(member, signal.SIGKILL)
                        if coordinator_alive:
                            signal_owned(batch["coordinator"], signal.SIGKILL)
                    elif not coordinator_alive:
                        for member in members:
                            if member not in sent:
                                signal_owned(member, signal.SIGTERM)
                                sent.add(member)
                    if not members and not coordinator_alive:
                        batch.update(status="stopped", reason="make stop 已停止本批次")
                        atomic_json(registry.batch_directory(batch_id) / "state.json", batch)
                        del state["batches"][batch_id]
            if now - started >= timing.graceful + timing.forced:
                raise DevError("停止超时；保留尚未退出的进程身份，请执行 make stop 重试。")
            time.sleep(0.1)
    finally:
        with registry.locked() as state:
            if state["stopping"] == asdict(owner):
                state["stopping"] = None


def stop_attached(
    registry: Registry,
    batch_id: str,
    process: subprocess.Popen[bytes],
    timing: Timing,
    *,
    failure: str = "",
) -> int:
    registry.request_stop(batch_id, failure=failure)
    clean = terminate_batch(registry, batch_id, timing.graceful, timing.forced)
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        batch = registry.read_batch(batch_id)
        if batch["coordinator"] is not None:
            signal_owned(batch["coordinator"], signal.SIGKILL)
        process.wait(timeout=timing.forced)
    if clean:
        registry.finish(batch_id, "failed" if failure else "stopped", failure or "前台停止请求")
    else:
        announce("本批次仍有进程未退出，保留登记；请执行 make stop 重试。")
    return 1 if failure or not clean else 0


def attach(
    registry: Registry,
    batch_id: str,
    process: subprocess.Popen[bytes],
    selected: list[Service],
    background: bool,
    timing: Timing = DEFAULT_TIMING,
    *,
    stop_event: threading.Event | None = None,
) -> int:
    directory = registry.batch_directory(batch_id)
    tails = {"协调器": LogTail(directory / "coordinator.log")}
    if not background:
        tails.update(
            {service.name: LogTail(directory / f"{service.name}.log") for service in selected}
        )
    signalled = stop_event if stop_event is not None else threading.Event()
    previous: dict[int, Any] = {}
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        previous[sig] = signal.signal(sig, lambda *_: signalled.set())
    reported = False
    deadline = float(registry.read_batch(batch_id)["accepted"]) + timing.startup
    try:
        while True:
            for name, tail in tails.items():
                for line in tail.lines():
                    print(f"[{name}] {line}", flush=True)
            if signalled.is_set():
                announce("收到停止请求，只停止本次启动的批次。")
                result = stop_attached(registry, batch_id, process, timing)
                for name, tail in tails.items():
                    for line in tail.lines():
                        print(f"[{name}] {line}", flush=True)
                return result
            batch = registry.read_batch(batch_id)
            if not reported and time.monotonic() >= deadline and process.poll() is None:
                reason = f"启动总超时（{timing.startup:g} 秒）；{batch['reason']}"
                announce(reason)
                return stop_attached(registry, batch_id, process, timing, failure=reason)
            if batch["status"] == "running" and not reported and process.poll() is None:
                for service in selected:
                    if service.port is not None:
                        suffix = "/docs" if service.expected_service else "/"
                        announce(f"{service.name} 访问地址：{service.url}{suffix}")
                    else:
                        announce("Worker：占位进程已启动（task_handlers=0），尚无任务处理能力。")
                announce(f"批次：{batch_id}；日志：{directory}；停止：make stop")
                reported = True
                if background:
                    return 0
                announce("前台运行中，Ctrl+C 停止本批次。")
            if process.poll() is not None:
                for name, tail in tails.items():
                    for line in tail.lines():
                        print(f"[{name}] {line}", flush=True)
                if batch["status"] not in ("stopped", "failed"):
                    announce("协调器意外退出，正在清理本批次。")
                    clean = terminate_batch(registry, batch_id, timing.graceful, timing.forced)
                    if clean:
                        registry.finish(batch_id, "failed", "协调器意外退出")
                    else:
                        announce("仍有进程未退出，保留登记；请执行 make stop 重试。")
                    return 1
                return 1 if not reported or batch["status"] == "failed" or process.returncode else 0
            time.sleep(0.1)
    finally:
        for signal_number, handler in previous.items():
            signal.signal(signal_number, handler)
