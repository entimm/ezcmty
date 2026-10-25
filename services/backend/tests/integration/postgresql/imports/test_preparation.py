from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest
from pytest import MonkeyPatch
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from tests.support.imports.adapter import TestRecordAdapter
from tests.support.imports.adapter import test_registry as make_registry
from tests.support.imports.data import ImportSetup
from tests.support.imports.pipeline import confirm_preview, drain_worker, source_batch

from backend_app.core.config import get_settings
from backend_app.core.identifiers import new_id
from backend_app.domain.admin.identity import AdminIdentity
from backend_app.domain.imports.types import ImportContext, ImportPreparation, ImportProblem
from backend_app.integrations.import_files.storage import LocalImportStorage
from backend_app.models.admin import utc_now
from backend_app.models.imports import ImportBatch, ImportOperation, ImportRow
from backend_app.repositories.imports import control, queries
from backend_app.repositories.imports.tasks import claim_tasks
from backend_app.services.worker.imports.pipeline import ImportWorkerService


class PreparedAdapter(TestRecordAdapter):
    generation = 1
    reject_reuse = False
    reject_fixed = False

    def prepare(
        self,
        row: Mapping[str, Any],
        context: ImportContext,
        db: Session,
        *,
        fixed_prepared: Mapping[str, Any] | None = None,
    ) -> ImportPreparation:
        prepared = (
            dict(fixed_prepared)
            if fixed_prepared is not None
            else {
                **row,
                "generation": self.generation,
            }
        )
        if fixed_prepared is not None and self.reject_fixed:
            return ImportPreparation(
                prepared, (ImportProblem("import.conflict", "原业务条件已变化"),)
            )
        return ImportPreparation(prepared, tuple(self.revalidate(prepared, context, db)))

    def required_permissions(
        self, normalized_input: Mapping[str, Any], prepared: Mapping[str, Any] | None = None
    ) -> frozenset[str]:
        return (
            frozenset({"platform.payment.recover"})
            if normalized_input.get("name") == "RESTRICTED"
            else frozenset()
        )

    def revalidate(
        self,
        row: Mapping[str, Any],
        context: ImportContext,
        db: Session,
        *,
        target: Mapping[str, str] | None = None,
    ) -> Sequence[ImportProblem]:
        if target is not None and self.reject_reuse:
            return (ImportProblem("import.conflict", "原业务目标已不可复用"),)
        return super().revalidate(row, context, db, target=target)


def _worker(setup: ImportSetup, tmp_path: Path, adapter: TestRecordAdapter) -> ImportWorkerService:
    return ImportWorkerService(
        setup.factory,
        get_settings(),
        make_registry(adapter),
        LocalImportStorage(tmp_path / "objects"),
    )


def _ledger(operation: ImportOperation) -> tuple[Any, ...]:
    return tuple(
        getattr(operation, name)
        for name in (
            "id",
            "status",
            "target_type",
            "target_id",
            "attempt_count",
            "last_attempt_at",
            "processed_at",
            "updated_at",
            "input_fingerprint",
            "operation_key",
        )
    )


def test_unconfirmed_recheck_replaces_preparation_without_mutating_old_operation(
    import_setup: ImportSetup,
    tmp_path: Path,
) -> None:
    adapter = PreparedAdapter()
    worker = _worker(import_setup, tmp_path, adapter)
    batch_id = source_batch(import_setup, worker.storage, "编码,名称\na,正常\n".encode())
    drain_worker(import_setup.factory, worker)
    with import_setup.factory() as db:
        row = db.scalars(select(ImportRow).where(ImportRow.batch_id == batch_id)).one()
        old_id, raw = row.operation_id, row.raw_values
        original = db.get(ImportOperation, old_id)
        assert original is not None
        old_ledger = _ledger(original)
        batch = db.get(ImportBatch, batch_id)
        assert batch is not None
        batch.status = "prechecking"
        control.task(
            db,
            batch,
            "precheck",
            {
                "schema_version": 1,
                "target_preview_version": 2,
                "next_row_no": 1,
            },
            utc_now(),
        )
        db.commit()
    adapter.generation = 2
    drain_worker(import_setup.factory, worker)
    with import_setup.factory() as db:
        batch = db.get(ImportBatch, batch_id)
        row = db.scalars(select(ImportRow).where(ImportRow.batch_id == batch_id)).one()
        assert batch is not None and batch.status == "preview_ready" and batch.preview_version == 2
        assert row.normalized_values is not None
        assert row.normalized_values["_prepared"]["generation"] == 2
        assert row.raw_values == raw and row.operation_id != old_id
        original = db.get(ImportOperation, old_id)
        assert original is not None and _ledger(original) == old_ledger


@pytest.mark.parametrize("invalidate_before_preview", [True, False])
def test_reuse_revalidation_never_rewrites_original_success(
    import_setup: ImportSetup,
    tmp_path: Path,
    invalidate_before_preview: bool,
) -> None:
    adapter = PreparedAdapter()
    worker = _worker(import_setup, tmp_path, adapter)
    first = source_batch(import_setup, worker.storage, "编码,名称\na,正常\n".encode())
    drain_worker(import_setup.factory, worker)
    confirm_preview(import_setup, first)
    drain_worker(import_setup.factory, worker)
    with import_setup.factory() as db:
        operation = db.scalars(select(ImportOperation)).one()
        original = _ledger(operation)
    second = source_batch(
        import_setup, worker.storage, "编码,名称\na,正常\n".encode(), install_business_table=False
    )
    adapter.reject_reuse = invalidate_before_preview
    drain_worker(import_setup.factory, worker)
    if not invalidate_before_preview:
        confirm_preview(import_setup, second)
        adapter.reject_reuse = True
        drain_worker(import_setup.factory, worker)
    with import_setup.factory() as db:
        operation = db.scalars(select(ImportOperation)).one()
        assert _ledger(operation) == original
        batch = db.get(ImportBatch, second)
        row = db.scalars(select(ImportRow).where(ImportRow.batch_id == second)).one()
        assert batch is not None
        if invalidate_before_preview:
            assert batch.status == "preview_ready" and batch.error_rows == 1
            assert row.operation_id is None and row.planned_action == "conflict"
        else:
            assert batch.status == "failed" and row.execution_status == "failed"
            assert queries.retryable_rows(db, batch) == []
        assert db.scalar(text("SELECT count(*) FROM import_test_records")) == 1


@pytest.mark.parametrize("valid_source", [True, False])
def test_condition_permissions_block_even_when_other_input_is_invalid(
    import_setup: ImportSetup,
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    valid_source: bool,
) -> None:
    original = AdminIdentity.effective_permissions
    monkeypatch.setattr(
        AdminIdentity,
        "effective_permissions",
        lambda self, account_id: [
            permission
            for permission in original(self, account_id)
            if permission != "platform.payment.recover"
        ],
    )
    worker = _worker(import_setup, tmp_path, PreparedAdapter())
    code = "a" if valid_source else "x" * 31
    batch_id = source_batch(
        import_setup, worker.storage, f"编码,名称\n{code},RESTRICTED\n".encode()
    )
    drain_worker(import_setup.factory, worker)
    with import_setup.factory() as db:
        batch = db.get(ImportBatch, batch_id)
        assert (
            batch is not None
            and batch.status == "blocked"
            and batch.last_error_code == "auth.forbidden"
        )
        assert batch.confirmed_at is None and batch.preview_version == 0
        assert db.scalar(text("SELECT count(*) FROM import_test_records")) == 0


@pytest.mark.parametrize("reject_fixed", [True, False])
def test_failed_retry_preserves_original_preparation_and_operation(
    import_setup: ImportSetup,
    tmp_path: Path,
    reject_fixed: bool,
) -> None:
    adapter = PreparedAdapter()
    worker = _worker(import_setup, tmp_path, adapter)
    first = source_batch(import_setup, worker.storage, "编码,名称\na,RETRY\n".encode())
    drain_worker(import_setup.factory, worker)
    confirm_preview(import_setup, first)
    drain_worker(import_setup.factory, worker)
    retry_id = new_id()
    with import_setup.factory() as db:
        parent = db.get(ImportBatch, first)
        row = db.scalars(select(ImportRow).where(ImportRow.batch_id == first)).one()
        assert parent is not None and parent.failed_rows == 1
        snapshot, operation_id = row.normalized_values, row.operation_id
        retry = ImportBatch(
            id=retry_id,
            parent_batch_id=first,
            property_company_id=parent.property_company_id,
            scope_type=parent.scope_type,
            scope_snapshot=parent.scope_snapshot,
            template_key=parent.template_key,
            template_version_no=parent.template_version_no,
            template_config_hash=parent.template_config_hash,
            created_by_scope=parent.created_by_scope,
            created_by_id=parent.created_by_id,
            request_id="fixed-retry",
            status="prechecking",
            retention_until=parent.retention_until,
        )
        db.add(retry)
        db.flush()
        db.add(
            ImportRow(
                batch_id=retry_id,
                source_row_no=row.source_row_no,
                raw_values=row.raw_values,
                normalized_values=snapshot,
                operation_id=operation_id,
            )
        )
        db.flush()
        control.recalculate(db, retry)
        control.task(
            db,
            retry,
            "precheck",
            {
                "schema_version": 1,
                "target_preview_version": 1,
                "next_row_no": 1,
            },
            utc_now(),
        )
        db.commit()
    adapter.generation, adapter.allow_retry, adapter.reject_fixed = 2, True, reject_fixed
    drain_worker(import_setup.factory, worker)
    with import_setup.factory() as db:
        retried_batch = db.get(ImportBatch, retry_id)
        row = db.scalars(select(ImportRow).where(ImportRow.batch_id == retry_id)).one()
        assert retried_batch is not None and retried_batch.status == "preview_ready", (
            retried_batch.last_error_code if retried_batch else None
        )
        assert row.normalized_values == snapshot and row.operation_id == operation_id
        assert retried_batch.error_rows == int(reject_fixed)
    if not reject_fixed:
        confirm_preview(import_setup, retry_id)
        drain_worker(import_setup.factory, worker)
        with import_setup.factory() as db:
            finished_retry = db.get(ImportBatch, retry_id)
            assert finished_retry is not None and finished_retry.created_rows == 1
            original = db.scalars(select(ImportRow).where(ImportRow.batch_id == first)).one()
            assert original.execution_status == "failed" and original.normalized_values == snapshot


def test_uncommitted_reuse_response_loss_does_not_demote_a_shared_success(
    import_setup: ImportSetup,
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    adapter = PreparedAdapter()
    worker = _worker(import_setup, tmp_path, adapter)
    first = source_batch(import_setup, worker.storage, "编码,名称\na,正常\n".encode())
    drain_worker(import_setup.factory, worker)
    confirm_preview(import_setup, first)
    drain_worker(import_setup.factory, worker)
    with import_setup.factory() as db:
        original = _ledger(db.scalars(select(ImportOperation)).one())
    second = source_batch(
        import_setup, worker.storage, "编码,名称\na,正常\n".encode(), install_business_table=False
    )
    drain_worker(import_setup.factory, worker)
    confirm_preview(import_setup, second)
    original_commit = Session.commit
    lost = False

    def commit(db: Session) -> None:
        nonlocal lost
        if not lost and any(
            isinstance(row, ImportRow)
            and row.batch_id == second
            and row.execution_status == "skipped"
            for row in db.identity_map.values()
        ):
            lost = True
            raise DBAPIError(
                "COMMIT", {}, RuntimeError("response lost"), connection_invalidated=True
            )
        original_commit(db)

    monkeypatch.setattr(Session, "commit", commit)
    drain_worker(import_setup.factory, worker)
    with import_setup.factory() as db:
        batch = db.get(ImportBatch, second)
        assert lost and batch is not None and batch.status == "completed"
        assert batch.skipped_rows == 1 and batch.uncertain_rows == 0
        assert _ledger(db.scalars(select(ImportOperation)).one()) == original
        assert db.scalar(text("SELECT count(*) FROM import_test_records")) == 1


def test_uncertain_row_with_shared_success_still_revalidates_the_target(
    import_setup: ImportSetup,
    tmp_path: Path,
) -> None:
    adapter = PreparedAdapter()
    worker = _worker(import_setup, tmp_path, adapter)
    first = source_batch(import_setup, worker.storage, "编码,名称\na,正常\n".encode())
    drain_worker(import_setup.factory, worker)
    confirm_preview(import_setup, first)
    drain_worker(import_setup.factory, worker)
    with import_setup.factory() as db:
        original = _ledger(db.scalars(select(ImportOperation)).one())
    second = source_batch(
        import_setup, worker.storage, "编码,名称\na,正常\n".encode(), install_business_table=False
    )
    drain_worker(import_setup.factory, worker)
    confirm_preview(import_setup, second)
    with import_setup.factory() as db:
        batch = db.get(ImportBatch, second)
        row = db.scalars(select(ImportRow).where(ImportRow.batch_id == second)).one()
        assert batch is not None
        row.execution_status, row.result_at = "uncertain", utc_now()
        batch.status, batch.last_error_code = "blocked", "import.result_uncertain"
        control.recalculate(db, batch)
        db.commit()
    adapter.reject_reuse = True
    drain_worker(import_setup.factory, worker)
    with import_setup.factory() as db:
        batch = db.get(ImportBatch, second)
        row = db.scalars(select(ImportRow).where(ImportRow.batch_id == second)).one()
        assert batch is not None and batch.status == "failed" and batch.uncertain_rows == 0
        assert row.execution_status == "failed" and queries.retryable_rows(db, batch) == []
        assert _ledger(db.scalars(select(ImportOperation)).one()) == original


def test_persisted_cancel_can_finish_after_creator_loses_write_permission(
    import_setup: ImportSetup,
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    worker = _worker(import_setup, tmp_path, PreparedAdapter())
    batch_id = source_batch(import_setup, worker.storage, "编码,名称\na,正常\n".encode())
    drain_worker(import_setup.factory, worker)
    confirm_preview(import_setup, batch_id)
    with import_setup.factory() as db:
        lease = claim_tasks(db, now=utc_now())[0]
        batch = db.get(ImportBatch, batch_id)
        assert batch is not None
        batch.status, batch.cancel_requested_at = "cancel_requested", utc_now()
        db.commit()
    monkeypatch.setattr(AdminIdentity, "effective_permissions", lambda self, account_id: [])
    worker.run(lease)
    with import_setup.factory() as db:
        batch = db.get(ImportBatch, batch_id)
        assert batch is not None and batch.status == "cancelled" and batch.cancelled_rows == 1
        assert db.scalar(text("SELECT count(*) FROM import_test_records")) == 0


def test_identifiable_duplicate_invalid_input_also_excludes_the_valid_row(
    import_setup: ImportSetup,
    tmp_path: Path,
) -> None:
    worker = _worker(import_setup, tmp_path, TestRecordAdapter())
    batch_id = source_batch(
        import_setup, worker.storage, ("编码,名称\na,正常\na," + "x" * 81 + "\n").encode()
    )
    drain_worker(import_setup.factory, worker)
    with import_setup.factory() as db:
        batch = db.get(ImportBatch, batch_id)
        assert batch is not None and batch.status == "preview_ready" and batch.error_rows == 2
        rows = db.scalars(select(ImportRow).where(ImportRow.batch_id == batch_id)).all()
        assert all(row.operation_id is None and row.planned_action == "conflict" for row in rows)
        assert queries.selected_count(db, batch, True) == 0
        assert db.scalar(text("SELECT count(*) FROM import_test_records")) == 0
