from __future__ import annotations

import subprocess
from pathlib import Path

from tests.support.dev import Harness


def typecheck(frontend: Path) -> subprocess.CompletedProcess[str]:
    from scripts.dev.processes import subprocess_environment

    (frontend / "src" / "Home.tsx").write_text(
        "import { useLocation } from '@umijs/max';\n"
        "export default function Home() { return <main>{useLocation().pathname}</main>; }\n"
    )
    return subprocess.run(
        ["pnpm", "typecheck"],
        cwd=frontend,
        env=subprocess_environment(),
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_typecheck_generates_types_without_starting_dev_server(harness: Harness) -> None:
    frontend = Path(harness.admin().cwd)
    contract_types = harness.registry.root / "openapi" / "types.d.ts"
    assert not contract_types.exists()

    result = typecheck(frontend)

    assert result.returncode == 0, result.stdout + result.stderr
    assert contract_types.is_file()
    assert (frontend / "src" / ".umi-types" / "exports.ts").is_file()
    assert not (frontend / "src" / ".umi").exists()


def test_typecheck_preserves_running_dev_server_files(harness: Harness) -> None:
    from scripts.dev.services import http_probe

    service = harness.admin()
    frontend = Path(service.cwd)
    batch, coordinator = harness.start([service])
    harness.ready(batch)
    generated = frontend / "src" / ".umi"
    sentinel = generated / "setup-sentinel"
    sentinel.write_text("owned by the running dev server")

    result = typecheck(frontend)

    assert result.returncode == 0, result.stdout + result.stderr
    assert sentinel.read_text() == "owned by the running dev server"
    assert (generated / "umi.ts").is_file()
    assert (generated / "exports.ts").is_file()
    assert coordinator.poll() is None
    assert http_probe(service, 10)["ok"]
