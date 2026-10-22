from pathlib import Path

import pytest
from sqlalchemy import func, select, text
from tests.support.imports.adapter import TestRecordAdapter
from tests.support.imports.adapter import test_registry as make_registry
from tests.support.imports.data import ImportSetup
from tests.support.imports.pipeline import confirm_preview, drain_worker, source_batch

from backend_app.core.config import get_settings
from backend_app.integrations.import_files.storage import LocalImportStorage
from backend_app.models.imports import (
    ImportBatch,
    ImportIssue,
    ImportOperation,
    ImportRow,
    ImportTask,
)
from backend_app.services.worker.imports.pipeline import ImportWorkerService


def test_parse_preview_has_no_business_write_and_execution_obeys_selection(
    import_setup: ImportSetup,
    tmp_path: Path,
) -> None:
    storage = LocalImportStorage(tmp_path / "objects")
    worker = ImportWorkerService(import_setup.factory, get_settings(), make_registry(), storage)
    batch_id = source_batch(
        import_setup, storage, "编码,名称\n a ,正常\nb,WARNING\nc,INVALID\n".encode()
    )
    assert drain_worker(import_setup.factory, worker) == 2
    with import_setup.factory() as db:
        batch = db.get(ImportBatch, batch_id)
        assert batch is not None
        assert batch.status == "preview_ready", batch.last_error_code
        assert (
            batch.total_rows,
            batch.planned_create_rows,
            batch.warning_rows,
            batch.error_rows,
        ) == (3, 2, 1, 1)
        assert db.scalar(text("SELECT count(*) FROM import_test_records")) == 0
    confirm_preview(import_setup, batch_id)
    drain_worker(import_setup.factory, worker)
    with import_setup.factory() as db:
        batch = db.get(ImportBatch, batch_id)
        assert batch is not None
        assert batch.status == "completed", batch.last_error_code
        assert (batch.created_rows, batch.processed_rows) == (1, 3)
        assert db.scalar(text("SELECT count(*) FROM import_test_records")) == 1
        assert db.scalars(
            select(ImportRow.execution_status)
            .where(ImportRow.batch_id == batch_id)
            .order_by(ImportRow.source_row_no)
        ).all() == ["created", "excluded", "excluded"]


@pytest.mark.parametrize("source", ["编码,名称\na,第一\na,第一\n", "编码,名称\na,第一\na,第二\n"])
def test_duplicate_natural_keys_are_rejected_even_when_inputs_differ(
    import_setup: ImportSetup,
    tmp_path: Path,
    source: str,
) -> None:
    storage = LocalImportStorage(tmp_path / "objects")
    worker = ImportWorkerService(import_setup.factory, get_settings(), make_registry(), storage)
    batch_id = source_batch(import_setup, storage, source.encode())
    drain_worker(import_setup.factory, worker)
    with import_setup.factory() as db:
        batch = db.get(ImportBatch, batch_id)
        assert batch is not None
        assert batch.status == "preview_ready", batch.last_error_code
        assert batch.error_rows == 2
        assert (
            db.scalar(
                select(func.count())
                .select_from(ImportIssue)
                .where(
                    ImportIssue.batch_id == batch_id, ImportIssue.code == "import.duplicate_in_file"
                )
            )
            == 2
        )
        assert db.scalars(
            select(ImportRow.operation_id).where(ImportRow.batch_id == batch_id)
        ).all() == [None, None]


def test_shared_success_is_reused_without_changing_success_ledger(
    import_setup: ImportSetup,
    tmp_path: Path,
) -> None:
    storage = LocalImportStorage(tmp_path / "objects")
    worker = ImportWorkerService(import_setup.factory, get_settings(), make_registry(), storage)
    one = source_batch(import_setup, storage, "编码,名称\na,正常\n".encode())
    drain_worker(import_setup.factory, worker)
    confirm_preview(import_setup, one)
    drain_worker(import_setup.factory, worker)
    two = source_batch(
        import_setup, storage, "编码,名称\na,正常\n".encode(), install_business_table=False
    )
    drain_worker(import_setup.factory, worker)
    confirm_preview(import_setup, two)
    drain_worker(import_setup.factory, worker)
    with import_setup.factory() as db:
        original, retry = db.get(ImportBatch, one), db.get(ImportBatch, two)
        assert original is not None and retry is not None
        assert original.created_rows == 1 and retry.skipped_rows == 1
        assert retry.status == "completed", retry.last_error_code
        assert db.scalars(select(ImportOperation.status)).all() == ["succeeded"]
        assert db.scalar(text("SELECT count(*) FROM import_test_records")) == 1


def test_unknown_result_remains_blocked_until_original_key_is_verified(
    import_setup: ImportSetup,
    tmp_path: Path,
) -> None:
    adapter = TestRecordAdapter()
    adapter.unknown = True
    storage = LocalImportStorage(tmp_path / "objects")
    worker = ImportWorkerService(
        import_setup.factory, get_settings(), make_registry(adapter), storage
    )
    batch_id = source_batch(import_setup, storage, "编码,名称\na,UNKNOWN\n".encode())
    drain_worker(import_setup.factory, worker)
    confirm_preview(import_setup, batch_id)
    drain_worker(import_setup.factory, worker)
    with import_setup.factory() as db:
        batch = db.get(ImportBatch, batch_id)
        assert batch is not None
        assert batch.status == "blocked" and batch.uncertain_rows == 1
        assert batch.finished_at is None
        operation = db.scalars(select(ImportOperation)).one()
        # A recovered external fact is looked up by the exact original logical operation key.
        db.execute(
            text(
                "INSERT INTO import_test_records VALUES "
                "(gen_random_uuid(),:company,'A','UNKNOWN',:key)"
            ),
            {"company": import_setup.company_id, "key": operation.operation_key},
        )
        task = db.scalars(
            select(ImportTask).where(ImportTask.batch_id == batch_id, ImportTask.phase == "apply")
        ).one()
        task.status = "ready"
        task.last_error_code = None
        db.commit()
    drain_worker(import_setup.factory, worker)
    with import_setup.factory() as db:
        batch = db.get(ImportBatch, batch_id)
        assert batch is not None
        assert batch.status == "completed" and batch.uncertain_rows == 0
        assert batch.created_rows == 1
        assert db.scalar(text("SELECT count(*) FROM import_test_records")) == 1


def test_cancel_after_claim_preserves_shared_operations_and_stops_pending_rows(
    import_setup: ImportSetup,
    tmp_path: Path,
) -> None:
    from backend_app.models.admin import utc_now
    from backend_app.repositories.imports.tasks import claim_tasks

    storage = LocalImportStorage(tmp_path / "objects")
    worker = ImportWorkerService(import_setup.factory, get_settings(), make_registry(), storage)
    batch_id = source_batch(import_setup, storage, "编码,名称\na,正常\nb,正常\n".encode())
    drain_worker(import_setup.factory, worker)
    confirm_preview(import_setup, batch_id)
    with import_setup.factory() as db:
        lease = claim_tasks(db, now=utc_now())[0]
        db.commit()
    with import_setup.factory() as db:
        batch = db.get(ImportBatch, batch_id)
        assert batch is not None
        batch.status = "cancel_requested"
        batch.cancel_requested_at = utc_now()
        db.commit()
    worker.run(lease)
    with import_setup.factory() as db:
        batch = db.get(ImportBatch, batch_id)
        assert batch is not None
        assert batch.status == "cancelled" and batch.cancelled_rows == 2
        assert db.scalars(select(ImportOperation.status)).all() == ["ready", "ready"]
        assert db.scalar(text("SELECT count(*) FROM import_test_records")) == 0


def test_submit_response_lost_recovers_committed_results_without_duplicate_create(
    import_setup: ImportSetup,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sqlalchemy.exc import DBAPIError
    from sqlalchemy.orm import Session

    storage = LocalImportStorage(tmp_path / "objects")
    worker = ImportWorkerService(import_setup.factory, get_settings(), make_registry(), storage)
    batch_id = source_batch(import_setup, storage, "编码,名称\na,正常\n".encode())
    drain_worker(import_setup.factory, worker)
    confirm_preview(import_setup, batch_id)
    original = Session.commit
    lost = False

    def commit(db: Session) -> None:
        nonlocal lost
        committed_row = any(
            isinstance(value, ImportRow) and value.execution_status == "created"
            for value in db.identity_map.values()
        )
        original(db)
        if committed_row and not lost:
            lost = True
            raise DBAPIError(
                "COMMIT", {}, RuntimeError("test response lost"), connection_invalidated=True
            )

    monkeypatch.setattr(Session, "commit", commit)
    drain_worker(import_setup.factory, worker)
    assert lost
    with import_setup.factory() as db:
        batch = db.get(ImportBatch, batch_id)
        assert batch is not None
        assert batch.status == "completed" and batch.uncertain_rows == 0
        assert db.scalars(select(ImportOperation.attempt_count)).all() == [1]
        assert db.scalar(text("SELECT count(*) FROM import_test_records")) == 1


def test_expired_lease_after_business_execute_rolls_back_business_and_checkpoint(
    import_setup: ImportSetup,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from collections.abc import Mapping
    from datetime import timedelta
    from typing import Any

    from sqlalchemy.orm import Session

    from backend_app.domain.imports.types import ImportContext, ImportPlan
    from backend_app.models.admin import utc_now
    from backend_app.repositories.imports.tasks import LeaseLost, claim_tasks

    current = utc_now()

    class ExpiringAdapter(TestRecordAdapter):
        def execute(
            self, plan: ImportPlan, context: ImportContext, db: Session
        ) -> Mapping[str, Any]:
            nonlocal current
            result = super().execute(plan, context, db)
            current += timedelta(seconds=31)
            return result

    storage = LocalImportStorage(tmp_path / "objects")
    worker = ImportWorkerService(
        import_setup.factory, get_settings(), make_registry(ExpiringAdapter()), storage
    )
    batch_id = source_batch(import_setup, storage, "编码,名称\na,正常\n".encode())
    drain_worker(import_setup.factory, worker)
    confirm_preview(import_setup, batch_id)
    current = utc_now()
    with import_setup.factory() as db:
        lease = claim_tasks(db, now=current)[0]
        db.commit()
    monkeypatch.setattr("backend_app.services.worker.imports.pipeline.utc_now", lambda: current)
    with pytest.raises(LeaseLost):
        worker.run(lease)
    with import_setup.factory() as db:
        assert db.scalar(text("SELECT count(*) FROM import_test_records")) == 0
        assert db.scalars(select(ImportRow.execution_status)).all() == ["pending"]
        assert db.scalars(select(ImportOperation.status)).all() == ["ready"]
        task = db.get(ImportTask, lease.id)
        assert task is not None and task.checkpoint["next_row_no"] == 1


def test_expired_unknown_recovery_only_verifies_original_result_and_stops_remaining_input(
    import_setup: ImportSetup,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import timedelta

    from backend_app.models.admin import utc_now

    adapter = TestRecordAdapter()
    adapter.unknown = True
    storage = LocalImportStorage(tmp_path / "objects")
    worker = ImportWorkerService(
        import_setup.factory, get_settings(), make_registry(adapter), storage
    )
    batch_id = source_batch(import_setup, storage, "编码,名称\na,UNKNOWN\nb,正常\n".encode())
    drain_worker(import_setup.factory, worker)
    confirm_preview(import_setup, batch_id)
    drain_worker(import_setup.factory, worker)
    with import_setup.factory() as db:
        batch = db.get(ImportBatch, batch_id)
        assert batch is not None
        assert batch.status == "blocked"
        later = batch.retention_until + timedelta(seconds=1)
        operation = db.scalars(
            select(ImportOperation).where(ImportOperation.status == "uncertain")
        ).one()
        db.execute(
            text(
                "INSERT INTO import_test_records VALUES "
                "(gen_random_uuid(),:company,'A','UNKNOWN',:key)"
            ),
            {"company": import_setup.company_id, "key": operation.operation_key},
        )
        task = db.scalars(
            select(ImportTask).where(ImportTask.batch_id == batch_id, ImportTask.phase == "apply")
        ).one()
        task.status = "ready"
        task.next_run_at = utc_now()
        db.commit()
    monkeypatch.setattr("backend_app.services.worker.imports.pipeline.utc_now", lambda: later)
    from backend_app.repositories.imports.tasks import claim_tasks

    with import_setup.factory() as db:
        lease = claim_tasks(db, now=later)[0]
        db.commit()
    worker.run(lease)
    with import_setup.factory() as db:
        batch = db.get(ImportBatch, batch_id)
        assert batch is not None
        assert batch.status == "expired" and batch.uncertain_rows == 0
        assert (batch.created_rows, batch.cancelled_rows) == (1, 1)
        assert batch.last_error_code == "import.data_expired"
        assert db.scalar(text("SELECT count(*) FROM import_test_records")) == 1


@pytest.mark.parametrize("format_name", ["csv", "xlsx"])
def test_error_file_generations_publish_complete_safe_projection(
    import_setup: ImportSetup,
    tmp_path: Path,
    format_name: str,
) -> None:
    from backend_app.models.admin import utc_now
    from backend_app.models.imports import ImportArtifact
    from backend_app.repositories.imports import control

    storage = LocalImportStorage(tmp_path / "objects")
    worker = ImportWorkerService(import_setup.factory, get_settings(), make_registry(), storage)
    batch_id = source_batch(import_setup, storage, "编码,名称\na,WARNING\nb,INVALID\n".encode())
    drain_worker(import_setup.factory, worker)
    with import_setup.factory() as db:
        batch = db.get(ImportBatch, batch_id)
        assert batch is not None
        now = utc_now()
        control.task(
            db,
            batch,
            "artifact",
            {
                "schema_version": 1,
                "source_preview_version": batch.preview_version,
                "source_batch_row_version": batch.row_version,
                "output_generation": 1,
                "next_row_no": 1,
                "next_part_no": 1,
            },
            now,
        )
        control.event(
            db,
            batch,
            "error-file:1",
            "error_file_requested",
            now,
            actor_scope="platform_admin",
            actor_id=import_setup.actor_id,
            metadata={"generation": 1, "format": format_name},
        )
        db.commit()
    drain_worker(import_setup.factory, worker)
    with import_setup.factory() as db:
        artifact = db.scalar(
            select(ImportArtifact).where(
                ImportArtifact.batch_id == batch_id, ImportArtifact.artifact_kind == "error_rows"
            )
        )
        task = db.scalars(
            select(ImportTask).where(
                ImportTask.batch_id == batch_id, ImportTask.phase == "artifact"
            )
        ).one()
        assert artifact is not None, task.last_error_code
        storage.verify(
            artifact.storage_key, expected_sha256=artifact.sha256, expected_size=artifact.byte_size
        )
        assert artifact.row_count == 2 and task.status == "completed"


def test_original_confirmed_task_can_finish_safely_after_retention_deadline(
    import_setup: ImportSetup,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import timedelta

    from backend_app.repositories.imports.tasks import claim_tasks

    storage = LocalImportStorage(tmp_path / "objects")
    worker = ImportWorkerService(import_setup.factory, get_settings(), make_registry(), storage)
    batch_id = source_batch(import_setup, storage, "编码,名称\na,正常\n".encode())
    drain_worker(import_setup.factory, worker)
    confirm_preview(import_setup, batch_id)
    with import_setup.factory() as db:
        batch = db.get(ImportBatch, batch_id)
        assert batch is not None
        later = batch.retention_until + timedelta(seconds=1)
        lease = claim_tasks(db, now=later)[0]
        db.commit()
    monkeypatch.setattr("backend_app.services.worker.imports.pipeline.utc_now", lambda: later)
    worker.run(lease)
    with import_setup.factory() as db:
        batch = db.get(ImportBatch, batch_id)
        assert batch is not None and batch.status == "completed" and batch.created_rows == 1
        assert db.scalar(text("SELECT count(*) FROM import_test_records")) == 1


def test_cancel_waiting_for_inflight_commit_preserves_committed_row_and_cancels_next(
    import_setup: ImportSetup,
    tmp_path: Path,
) -> None:
    from collections.abc import Mapping
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from time import monotonic, sleep
    from typing import Any

    from sqlalchemy.orm import Session

    from backend_app.core.identifiers import new_id
    from backend_app.domain.imports.types import ImportContext, ImportPlan
    from backend_app.models.admin import utc_now
    from backend_app.repositories.imports.tasks import claim_tasks

    executing, release, cancellation_started = Event(), Event(), Event()

    class BlockingAdapter(TestRecordAdapter):
        def execute(
            self, plan: ImportPlan, context: ImportContext, db: Session
        ) -> Mapping[str, Any]:
            result = super().execute(plan, context, db)
            if plan.values["code"] == "A":
                executing.set()
                assert release.wait(timeout=10), (
                    "Cancellation race did not reach synchronization point"
                )
            return result

    storage = LocalImportStorage(tmp_path / "objects")
    worker = ImportWorkerService(
        import_setup.factory, get_settings(), make_registry(BlockingAdapter()), storage
    )
    batch_id = source_batch(import_setup, storage, "编码,名称\na,正常\nb,正常\n".encode())
    drain_worker(import_setup.factory, worker)
    confirm_preview(import_setup, batch_id)
    with import_setup.factory() as db:
        lease = claim_tasks(db, now=utc_now())[0]
        db.commit()
    application_name = "import_cancel_" + new_id()

    def cancel() -> None:
        with import_setup.factory() as db:
            db.execute(
                text("SELECT set_config('application_name',:name,true)"), {"name": application_name}
            )
            cancellation_started.set()
            batch = db.scalars(
                select(ImportBatch)
                .where(ImportBatch.id == batch_id)
                .with_for_update(of=ImportBatch)
            ).one()
            batch.status = "cancel_requested"
            batch.cancel_requested_at = utc_now()
            db.commit()

    with ThreadPoolExecutor(max_workers=2) as pool:
        execute_future = pool.submit(worker.run, lease)
        try:
            assert executing.wait(timeout=5)
            cancel_future = pool.submit(cancel)
            assert cancellation_started.wait(timeout=5)
            deadline = monotonic() + 5
            while True:
                with import_setup.factory() as db:
                    waiting = db.scalar(
                        text(
                            "SELECT EXISTS(SELECT 1 FROM pg_stat_activity "
                            "WHERE application_name=:name AND wait_event_type='Lock')"
                        ),
                        {"name": application_name},
                    )
                if waiting:
                    break
                assert monotonic() < deadline, (
                    "Cancellation did not wait for the in-flight row transaction"
                )
                sleep(0.01)
        finally:
            release.set()
        cancel_future.result(timeout=10)
        execute_future.result(timeout=10)
    with import_setup.factory() as db:
        batch = db.get(ImportBatch, batch_id)
        assert batch is not None and batch.status == "cancelled"
        assert (batch.created_rows, batch.cancelled_rows, batch.processed_rows) == (1, 1, 2)
        assert db.scalar(text("SELECT count(*) FROM import_test_records")) == 1
        assert db.scalars(
            select(ImportOperation.status).order_by(ImportOperation.created_at, ImportOperation.id)
        ).all() == ["succeeded", "ready"]


def test_nonretryable_system_failure_is_excluded_from_failed_row_retry_selection(
    import_setup: ImportSetup,
    tmp_path: Path,
) -> None:
    from collections.abc import Mapping
    from typing import Any

    from sqlalchemy.orm import Session

    from backend_app.domain.imports.errors import ImportExecutionFailure
    from backend_app.domain.imports.types import ImportContext, ImportPlan
    from backend_app.repositories.imports import queries

    class NonretryableAdapter(TestRecordAdapter):
        def execute(
            self, plan: ImportPlan, context: ImportContext, db: Session
        ) -> Mapping[str, Any]:
            raise ImportExecutionFailure("import.system_error", retryable=False)

    storage = LocalImportStorage(tmp_path / "objects")
    worker = ImportWorkerService(
        import_setup.factory, get_settings(), make_registry(NonretryableAdapter()), storage
    )
    batch_id = source_batch(import_setup, storage, "编码,名称\na,正常\n".encode())
    drain_worker(import_setup.factory, worker)
    confirm_preview(import_setup, batch_id)
    drain_worker(import_setup.factory, worker)
    with import_setup.factory() as db:
        batch = db.get(ImportBatch, batch_id)
        assert batch is not None and batch.status == "failed" and batch.failed_rows == 1
        assert queries.retryable_rows(db, batch) == []
        assert db.scalars(select(ImportIssue.code).where(ImportIssue.phase == "apply")).all() == [
            "import.execution_failed"
        ]
        assert db.scalar(text("SELECT count(*) FROM import_test_records")) == 0
