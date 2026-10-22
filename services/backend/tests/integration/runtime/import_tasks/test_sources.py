from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from threading import Event
from time import monotonic

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from tests.support.imports.data import ImportSetup, create_batch, provision_imports
from tests.support.payment_tasks import notification_task

from backend_app.models.admin import utc_now
from backend_app.models.imports import ImportTask
from backend_app.models.payments import PaymentTask
from backend_app.repositories.imports.tasks import (
    TaskLease as ImportLease,
)
from backend_app.repositories.imports.tasks import (
    complete_task as complete_import,
)
from backend_app.repositories.imports.tasks import (
    ensure_task as ensure_import,
)
from backend_app.repositories.imports.tasks import (
    require_current_lease as require_import,
)
from backend_app.repositories.imports.tasks import (
    reschedule_task,
)
from backend_app.repositories.payments.tasks import TaskLease as PaymentLease
from backend_app.repositories.payments.tasks import complete_task as complete_payment
from backend_app.tasks.handlers.imports import ImportHandlers
from backend_app.tasks.handlers.payments import PaymentHandlers
from backend_app.tasks.runner import run_worker
from backend_app.tasks.sources.imports import ImportTaskSource
from backend_app.tasks.sources.payments import PaymentTaskSource


@pytest.fixture
def setup(migrated_database_url: str) -> Iterator[ImportSetup]:
    engine = create_engine(migrated_database_url)
    try:
        yield provision_imports(sessionmaker(engine, expire_on_commit=False))
    finally:
        engine.dispose()


def _parse_task(setup: ImportSetup) -> str:
    batch_id = create_batch(setup)
    with setup.factory() as db:
        task = ensure_import(
            db,
            "parse",
            batch_id,
            now=utc_now(),
            checkpoint={
                "schema_version": 1,
                "source_artifact_generation": 1,
                "cursor": {"kind": "csv_record", "next_byte_offset": 0, "next_row_no": 2},
            },
        )
        task_id = task.id
        db.commit()
        return task_id


def test_continuing_import_chunks_yield_to_new_payments_without_starving_imports(
    setup: ImportSetup,
) -> None:
    _parse_task(setup)
    stop = Event()
    events: list[str] = []
    claims = 0
    payments = 0

    def import_chunk(lease: ImportLease) -> None:
        nonlocal claims
        claims += 1
        events.append("import")
        with setup.factory() as db:
            require_import(db, lease, now=utc_now())
            if claims < 12:
                reschedule_task(db, lease, now=utc_now(), next_run_at=utc_now())
            else:
                complete_import(db, lease, now=utc_now())
            db.commit()
        notification_task(setup.factory, now=utc_now(), key=f"payment-{claims}")

    def payment(lease: PaymentLease) -> None:
        nonlocal payments
        payments += 1
        events.append("payment")
        with setup.factory() as db:
            complete_payment(db, lease, now=utc_now())
            db.commit()
        if payments == 12:
            stop.set()

    sources = (
        PaymentTaskSource(PaymentHandlers(tasks={"notification_process": payment})),
        ImportTaskSource(ImportHandlers(tasks={"import_parse": import_chunk})),
    )
    run_worker(stop, factory=setup.factory, sources=sources, poll_seconds=0.01)
    assert events == ["import", "payment"] * 12
    with setup.factory() as db:
        task = db.scalars(select(ImportTask)).one()
        assert task.attempt_count == 12
        assert task.status == "completed"
        assert set(db.scalars(select(PaymentTask.status))) == {"completed"}


def test_import_heartbeat_renews_through_independent_database_session(setup: ImportSetup) -> None:
    task_id = _parse_task(setup)
    stop = Event()
    renewed = False

    def import_chunk(lease: ImportLease) -> None:
        nonlocal renewed
        deadline = monotonic() + 5
        interval = Event()
        # The runner committed its claim; the heartbeat can renew without the business session.
        while monotonic() < deadline:
            with setup.factory() as db:
                expiry = db.scalar(
                    select(ImportTask.lease_expires_at).where(ImportTask.id == task_id)
                )
            if expiry is not None and expiry > lease.lease_expires_at + timedelta(milliseconds=500):
                renewed = True
                break
            interval.wait(0.02)
        assert renewed
        with setup.factory() as db:
            complete_import(db, lease, now=utc_now())
            db.commit()
        stop.set()

    sources = (ImportTaskSource(ImportHandlers(tasks={"import_parse": import_chunk})),)
    run_worker(stop, factory=setup.factory, sources=sources, lease_seconds=3, poll_seconds=0.01)
    with setup.factory() as db:
        assert db.scalar(select(ImportTask.status).where(ImportTask.id == task_id)) == "completed"


@pytest.mark.slow
def test_real_fifty_thousand_row_parse_load_continues_to_service_payments(
    setup: ImportSetup,
    tmp_path: Path,
) -> None:
    from tests.support.imports.adapter import test_registry as fixture_registry

    from backend_app.core.config import get_settings
    from backend_app.integrations.import_files.storage import LocalImportStorage
    from backend_app.models.imports import ImportArtifact, ImportBatch, ImportRow
    from backend_app.services.worker.imports.pipeline import CHUNK_ROWS, ImportWorkerService

    registry = fixture_registry()
    definition = registry.get("test_records", 1)
    with setup.factory() as db:
        now = utc_now()
        batch = ImportBatch(
            property_company_id=setup.company_id,
            scope_type="company",
            scope_snapshot={"property_company_id": setup.company_id},
            template_key=definition.key,
            template_version_no=1,
            template_config_hash=definition.config_hash,
            created_by_scope="platform_admin",
            created_by_id=setup.actor_id,
            request_id="capacity",
            status="prechecking",
            created_at=now,
            retention_until=now + timedelta(days=30),
        )
        db.add(batch)
        db.flush()
        batch_id = batch.id
        db.commit()
    storage = LocalImportStorage(tmp_path / "objects")
    payload = ("编码,名称\n" + "".join(f"C{number},中文名称\n" for number in range(50000))).encode()
    stored = storage.write(f"{setup.company_id}/{batch_id}/source.csv", [payload])
    with setup.factory() as db:
        db.add(
            ImportArtifact(
                batch_id=batch_id,
                artifact_kind="source",
                generation=1,
                storage_key=stored.key,
                media_type="text/csv",
                sha256=stored.sha256,
                byte_size=stored.byte_size,
                expires_at=now + timedelta(days=30),
            )
        )
        ensure_import(
            db,
            "parse",
            batch_id,
            now=now,
            checkpoint={
                "schema_version": 1,
                "source_artifact_generation": 1,
                "cursor": {"kind": "csv_record", "next_byte_offset": 0, "next_row_no": 2},
            },
        )
        db.commit()
    service = ImportWorkerService(setup.factory, get_settings(), registry, storage)
    stop = Event()
    chunks = 0
    payment_at_chunks: list[int] = []
    max_chunks = (50000 + CHUNK_ROWS - 1) // CHUNK_ROWS

    def parse_chunk(lease: ImportLease) -> None:
        nonlocal chunks
        service.run(lease)
        chunks += 1
        with setup.factory() as db:
            task = db.get(ImportTask, lease.id)
            assert task is not None and task.status in {"ready", "completed"}
            assert task.attempt_count == chunks
        if chunks % 10 == 0 or chunks == max_chunks:
            notification_task(setup.factory, now=utc_now(), key=f"capacity-{chunks}")
        assert chunks <= max_chunks

    def payment(lease: PaymentLease) -> None:
        payment_at_chunks.append(chunks)
        with setup.factory() as db:
            complete_payment(db, lease, now=utc_now())
            db.commit()
        if chunks == max_chunks:
            stop.set()

    run_worker(
        stop,
        factory=setup.factory,
        sources=(
            PaymentTaskSource(PaymentHandlers(tasks={"notification_process": payment})),
            ImportTaskSource(ImportHandlers(tasks={"import_parse": parse_chunk})),
        ),
        poll_seconds=0.01,
        lease_seconds=3,
    )
    assert chunks == max_chunks
    assert payment_at_chunks == list(range(10, max_chunks + 1, 10))
    with setup.factory() as db:
        completed_batch = db.get(ImportBatch, batch_id)
        assert completed_batch is not None and completed_batch.total_rows == 50000
        rows = list(
            db.scalars(select(ImportRow.source_row_no).where(ImportRow.batch_id == batch_id))
        )
        assert len(rows) == len(set(rows)) == 50000
        task = db.scalars(select(ImportTask).where(ImportTask.phase == "parse")).one()
        assert task.status == "completed"
        assert task.checkpoint["cursor"]["next_row_no"] == 50002
