import os
import subprocess
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import Event
from time import monotonic

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from tests.support.imports.data import ImportSetup, provision_imports
from tests.support.imports.pipeline import source_batch
from tests.support.paths import BACKEND_ROOT
from tests.support.postgresql import stop_service

from backend_app.integrations.import_files.storage import LocalImportStorage
from backend_app.models.imports import ImportRow, ImportTask

pytestmark = pytest.mark.slow


@pytest.fixture
def setup(migrated_database_url: str) -> Iterator[ImportSetup]:
    engine = create_engine(migrated_database_url)
    try:
        yield provision_imports(sessionmaker(engine, expire_on_commit=False))
    finally:
        engine.dispose()


def _eventually(predicate: Callable[[], bool]) -> None:
    deadline = monotonic() + 12
    interval = Event()
    while monotonic() < deadline:
        if predicate():
            return
        interval.wait(0.02)
    raise AssertionError("Import worker condition timed out")


@contextmanager
def _worker(
    directory: Path, storage: Path, database_url: str, mode: str
) -> Iterator[subprocess.Popen[bytes]]:
    directory.mkdir()
    environment = {**os.environ, "APP_DATABASE_URL": database_url}
    with (directory / "worker.log").open("wb") as log:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "tests.support.imports.worker",
                mode,
                str(directory),
                str(storage),
            ],
            cwd=BACKEND_ROOT,
            env=environment,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            yield process
        finally:
            stop_service(process)


def _state(setup: ImportSetup, batch_id: str) -> tuple[str, int]:
    with setup.factory() as db:
        task = db.scalars(
            select(ImportTask).where(ImportTask.batch_id == batch_id, ImportTask.phase == "parse")
        ).one()
        return task.status, task.attempt_count


def test_import_process_crash_is_recovered_from_persisted_cursor_by_new_lease(
    setup: ImportSetup,
    migrated_database_url: str,
    tmp_path: Path,
) -> None:
    storage = LocalImportStorage(tmp_path / "objects")
    batch_id = source_batch(
        setup, storage, "编码,名称\nA,中文\n".encode(), install_business_table=False
    )
    with _worker(tmp_path / "crash", storage.root, migrated_database_url, "crash") as process:
        assert process.wait(timeout=10) == 23
    assert _state(setup, batch_id) == ("running", 1)
    with _worker(tmp_path / "takeover", storage.root, migrated_database_url, "complete") as process:
        _eventually(lambda: _state(setup, batch_id) == ("completed", 2))
        assert process.poll() is None
        process.terminate()
        assert process.wait(timeout=10) == 0
    with setup.factory() as db:
        rows = list(db.scalars(select(ImportRow).where(ImportRow.batch_id == batch_id)))
        assert len(rows) == 1 and rows[0].raw_values == {"code": "A", "name": "中文"}


def test_import_process_finishes_current_chunk_and_stops_before_claiming_next(
    setup: ImportSetup,
    migrated_database_url: str,
    tmp_path: Path,
) -> None:
    storage = LocalImportStorage(tmp_path / "objects")
    payload = ("编码,名称\n" + "".join(f"C{index},中文\n" for index in range(500))).encode()
    batch_id = source_batch(setup, storage, payload, install_business_table=False)
    directory = tmp_path / "graceful"
    with _worker(directory, storage.root, migrated_database_url, "hold") as process:
        _eventually(lambda: (directory / "entered").exists())
        process.terminate()
        _eventually(lambda: (directory / "stop_received").exists())
        (directory / "release").touch()
        assert process.wait(timeout=10) == 0
    assert _state(setup, batch_id) == ("ready", 1)
    with setup.factory() as db:
        rows = list(db.scalars(select(ImportRow).where(ImportRow.batch_id == batch_id)))
        assert 0 < len(rows) < 500
        task = db.scalars(select(ImportTask).where(ImportTask.batch_id == batch_id)).one()
        assert task.checkpoint["cursor"]["next_row_no"] == len(rows) + 2
