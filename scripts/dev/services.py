"""Development service definitions and isolated, read-only readiness probes."""

from __future__ import annotations

import json
import shutil
import socket
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from scripts.dev.processes import DevError


@dataclass(frozen=True)
class Timing:
    startup: float = 60
    probe: float = 10
    interval: float = 0.5
    graceful: float = 10
    forced: float = 5
    reload: float = 20


DEFAULT_TIMING = Timing()


@dataclass(frozen=True)
class Service:
    name: str
    command: list[str]
    cwd: str
    port: int | None = None
    expected_service: str | None = None
    worker: bool = False

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"


def services(root: Path, selected: list[str]) -> list[Service]:
    backend = root / "services" / "backend"
    definitions: dict[str, Service] = {}
    for name, module, service, port in (
        ("platform", "platform_admin_api", "platform-admin-api", 8001),
        ("property", "property_admin_api", "property-admin-api", 8002),
        ("resident", "resident_api", "resident-api", 8003),
        ("webhook", "webhook", "webhook", 8004),
    ):
        definitions[name] = Service(
            name,
            [
                sys.executable,
                "-m",
                "scripts.dev.api",
                f"backend_app.runtimes.{module}:app",
                str(port),
            ],
            str(backend),
            port,
            service,
        )
    definitions["worker"] = Service(
        "worker",
        [sys.executable, "-m", "backend_app.runtimes.worker"],
        str(backend),
        worker=True,
    )
    vite = root / "apps" / "admin-web" / "node_modules" / "vite" / "bin" / "vite.js"
    definitions["admin"] = Service(
        "admin",
        [
            shutil.which("node") or "node",
            str(vite),
            "--host",
            "127.0.0.1",
            "--port",
            "5173",
            "--strictPort",
        ],
        str(root / "apps" / "admin-web"),
        5173,
    )
    names = list(definitions) if selected == ["all"] else selected
    if not names or len(set(names)) != len(names) or any(name not in definitions for name in names):
        raise DevError("服务名称无效；使用 make help 查看可用入口。")
    return [definitions[name] for name in names]


def check_ports(selected: list[Service]) -> None:
    for service in selected:
        if service.port is None:
            continue
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                listener.bind(("127.0.0.1", service.port))
            except OSError as exc:
                raise DevError(
                    f"{service.name}：端口 {service.port} 无法使用（{exc.strerror}）。"
                    "请自行确认占用进程；开发入口不会接管或更换端口。"
                ) from exc


def dependency_probe() -> dict[str, Any]:
    from pydantic import ValidationError

    from backend_app.core.config import get_settings
    from backend_app.services.system import check_readiness

    try:
        settings = get_settings()
    except ValidationError as exc:
        fields = ", ".join(".".join(map(str, error["loc"])) or "配置" for error in exc.errors())
        return {
            "ok": False,
            "fatal": True,
            "reason": f"后端配置无效（{fields}）；检查 services/backend/.env 或 APP_* 环境变量。",
        }
    dependencies = check_readiness()
    unavailable = [name for name, status in dependencies.items() if status != "ok"]
    return {
        "ok": not unavailable,
        "reason": "MySQL、Redis 只读依赖检查通过"
        if not unavailable
        else f"依赖不可用：{', '.join(unavailable)}；请确认本机实例及已有数据库和账号配置。",
        "log_level": settings.log_level,
    }


def http_probe(service: Service, timeout: float) -> dict[str, Any]:
    path = "/readyz" if service.expected_service is not None else "/"
    # Ignore shell proxy settings for loopback probes.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(service.url + path, timeout=timeout) as response:
            body = response.read(65_537)
            if len(body) > 65_536 or response.status != 200:
                return {"ok": False, "reason": "HTTP 页面或就绪响应无效"}
            if service.expected_service is None:
                ok = "text/html" in response.headers.get("Content-Type", "") and bool(body)
                return {"ok": ok, "reason": "HTTP 页面可访问" if ok else "未返回 HTML 页面"}
            document = json.loads(body)
            if not isinstance(document, dict):
                return {"ok": False, "reason": "/readyz 未返回对象"}
            if document.get("service") != service.expected_service:
                return {"ok": False, "reason": "/readyz 服务标识与目标不一致"}
            ready = document.get("status") == "ok" and document.get("dependencies") == {
                "mysql": "ok",
                "redis": "ok",
            }
            return {"ok": ready, "reason": "API 及依赖已就绪" if ready else "/readyz 依赖未就绪"}
    except urllib.error.HTTPError as exc:
        return {"ok": False, "reason": f"{path} 返回 HTTP {exc.code}"}
    except (OSError, ValueError, urllib.error.URLError):
        return {"ok": False, "reason": f"{path} 暂不可访问或响应无效"}


def probe_command(service: Service, timing: Timing) -> list[str]:
    return [
        sys.executable,
        "-m",
        "scripts.dev.services",
        "http",
        json.dumps(asdict(service)),
        str(timing.probe),
    ]


def main() -> None:
    if sys.argv[1] == "dependencies":
        result = dependency_probe()
    else:
        result = http_probe(Service(**json.loads(sys.argv[2])), float(sys.argv[3]))
    result["finished"] = time.monotonic()
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
