"""Subprocess acceptance harness that composes the real bounded import Worker service."""

import argparse
import os
import signal
from pathlib import Path
from threading import Event

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend_app.core.config import get_settings
from backend_app.core.logging import configure_logging
from backend_app.integrations.import_files.storage import LocalImportStorage
from backend_app.repositories.imports.tasks import TaskLease
from backend_app.services.worker.imports.pipeline import ImportWorkerService
from backend_app.tasks.handlers.imports import ImportHandlers
from backend_app.tasks.runner import run_worker
from backend_app.tasks.sources.imports import ImportTaskSource
from tests.support.imports.adapter import test_registry as fixture_registry


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("complete", "hold", "crash"))
    parser.add_argument("directory", type=Path)
    parser.add_argument("storage", type=Path)
    args = parser.parse_args()
    directory: Path = args.directory
    stop = Event()

    def stop_worker(*args: object) -> None:
        stop.set()
        (directory / "stop_received").touch()

    signal.signal(signal.SIGTERM, stop_worker)
    signal.signal(signal.SIGINT, stop_worker)
    configure_logging("INFO", "import-worker-test")
    engine = create_engine(os.environ["APP_DATABASE_URL"])
    factory = sessionmaker(engine, expire_on_commit=False)
    service = ImportWorkerService(
        factory, get_settings(), fixture_registry(), LocalImportStorage(args.storage)
    )

    def parse(lease: TaskLease) -> None:
        (directory / "entered").write_text(lease.id)
        if args.mode == "crash":
            os._exit(23)
        if args.mode == "hold":
            interval = Event()
            while not (directory / "release").exists():
                interval.wait(0.02)
        service.run(lease)

    try:
        run_worker(
            stop,
            factory=factory,
            sources=(ImportTaskSource(ImportHandlers(tasks={"import_parse": parse})),),
            poll_seconds=0.02,
            lease_seconds=3,
        )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
