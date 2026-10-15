from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
from pytest import MonkeyPatch
from tests.support.dev import ROOT, Harness


@pytest.fixture
def harness(tmp_path: Path, monkeypatch: MonkeyPatch) -> Generator[Harness]:
    monkeypatch.syspath_prepend(str(ROOT))
    from scripts.dev.processes import Registry
    from scripts.dev.services import Timing

    source = tmp_path / "backend" / "src"
    source.mkdir(parents=True)
    monkeypatch.setenv("PYTHONPATH", str(source))
    monkeypatch.setenv("APP_LOG_LEVEL", "INFO")
    result = Harness(
        Registry(tmp_path),
        Timing(startup=8, probe=2, interval=0.1, graceful=1, forced=2, reload=4),
        source,
    )
    try:
        yield result
    finally:
        result.close()
