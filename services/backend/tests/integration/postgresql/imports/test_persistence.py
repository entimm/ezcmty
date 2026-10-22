from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from tests.support.imports.data import NOW, ImportSetup, create_batch

from backend_app.models.imports import ImportBatch, ImportRow
from backend_app.repositories.imports.events import append_event
from backend_app.repositories.imports.issues import add_issue, page_issues
from backend_app.repositories.imports.requests import (
    IdempotencyConflict,
    find_request,
    record_request,
)
from backend_app.repositories.imports.rows import page_rows, stage_rows
from backend_app.repositories.imports.tasks import (
    LeaseLost,
    TaskLease,
    advance_checkpoint,
    claim_tasks,
    ensure_task,
    renew_task,
    require_current_lease,
)


def test_rows_and_null_location_issues_replay_without_duplicates(import_setup: ImportSetup) -> None:
    batch_id = create_batch(import_setup)
    with import_setup.factory() as db:
        batch = db.get(ImportBatch, batch_id)
        assert batch is not None and batch.preview_version == 0 and batch.row_version == 1
        stage_rows(db, batch_id, [(2, {"code": "first"}), (4, {"code": "second"})], now=NOW)
        stage_rows(db, batch_id, [(2, {"code": "first"})], now=NOW)
        for _ in range(2):
            add_issue(
                db,
                batch_id=batch_id,
                preview_version=0,
                phase="parse",
                severity="error",
                code="import.header_mismatch",
                message="Invalid columns",
                created_at=NOW,
            )
        db.commit()
    with import_setup.factory() as db:
        rows, total = page_rows(db, batch_id, page=50)
        assert rows == [] and total == 2
        issues, count = page_issues(db, batch_id, preview_version=1)
        assert count == 1 and issues[0].preview_version == 0


def test_cross_batch_issue_row_reference_is_rejected(import_setup: ImportSetup) -> None:
    one, two = create_batch(import_setup), create_batch(import_setup)
    with import_setup.factory() as db:
        stage_rows(db, one, [(2, {"code": "one"})], now=NOW)
        row = db.scalars(select(ImportRow).where(ImportRow.batch_id == one)).one()
        with pytest.raises(IntegrityError):
            add_issue(
                db,
                batch_id=two,
                row_id=row.id,
                preview_version=1,
                phase="precheck",
                severity="error",
                code="import.scope_mismatch",
                message="Wrong scope",
                created_at=NOW,
            )


def test_request_replay_conflict_and_immutable_evidence(import_setup: ImportSetup) -> None:
    batch_id = create_batch(import_setup)
    identity = {
        "property_company_id": import_setup.company_id,
        "actor_scope": "platform_admin",
        "actor_id": import_setup.actor_id,
        "request_scope": "create",
        "idempotency_key": "one",
    }
    with import_setup.factory() as db:
        record_request(
            db,
            **identity,
            request_fingerprint="a" * 64,
            batch_id=batch_id,
            http_status=201,
            response_body={"id": batch_id},
            now=NOW,
        )
        db.commit()
    with import_setup.factory() as db:
        replay = find_request(db, **identity, request_fingerprint="a" * 64)
        assert replay is not None and replay.response_body == {"id": batch_id}
        with pytest.raises(IdempotencyConflict):
            find_request(db, **identity, request_fingerprint="b" * 64)
        replay.http_status = 202
        with pytest.raises(IntegrityError):
            db.flush()


def test_events_append_once_with_batch_sequence(import_setup: ImportSetup) -> None:
    batch_id = create_batch(import_setup)
    with import_setup.factory() as db:
        one = append_event(
            db,
            batch_id=batch_id,
            event_key="created",
            event_type="batch_created",
            now=NOW,
            safe_metadata={"total_rows": 0},
        )
        replay = append_event(
            db, batch_id=batch_id, event_key="created", event_type="batch_created", now=NOW
        )
        two = append_event(
            db, batch_id=batch_id, event_key="uploaded", event_type="source_uploaded", now=NOW
        )
        assert one.id == replay.id and (one.sequence_no, two.sequence_no) == (1, 2)
        db.commit()


def test_task_claim_race_and_expired_generation_protect_checkpoint(
    import_setup: ImportSetup,
) -> None:
    batch_id = create_batch(import_setup)
    with import_setup.factory() as db:
        ensure_task(
            db,
            "precheck",
            batch_id,
            now=NOW,
            checkpoint={"schema_version": 1, "target_preview_version": 1, "next_row_no": 2},
        )
        db.commit()
    barrier = Barrier(2)

    def claim() -> tuple[TaskLease, ...]:
        with import_setup.factory() as db:
            barrier.wait(timeout=5)
            result = claim_tasks(db, now=NOW)
            db.commit()
            return result

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(lambda _: claim(), range(2)))
    leases = [lease for result in results for lease in result]
    assert len(leases) == 1
    old = leases[0]
    later = NOW + timedelta(seconds=31)
    with import_setup.factory() as db:
        current = claim_tasks(db, now=later)[0]
        db.commit()
    assert current.attempt_count == 2
    with import_setup.factory() as db, pytest.raises(LeaseLost):
        renew_task(db, old, now=later)
    with import_setup.factory() as db:
        advance_checkpoint(
            db,
            current,
            now=later,
            progress_done=1,
            progress_total=2,
            checkpoint={"schema_version": 1, "target_preview_version": 1, "next_row_no": 5},
        )
        db.rollback()
    with import_setup.factory() as db:
        task = require_current_lease(db, current, now=later)
        assert task.checkpoint["next_row_no"] == 2 and task.progress_done == 0


def test_concurrent_operation_creation_resolves_one_durable_identity(
    import_setup: ImportSetup,
) -> None:
    from sqlalchemy import func

    from backend_app.models.imports import ImportOperation
    from backend_app.repositories.imports.operations import ensure_operation

    barrier = Barrier(2)

    def create() -> str:
        with import_setup.factory() as db:
            barrier.wait(timeout=5)
            operation = ensure_operation(
                db,
                property_company_id=import_setup.company_id,
                operation_key="c" * 64,
                operation_type="test.create",
                natural_key={"code": "one"},
                input_fingerprint="d" * 64,
                now=NOW,
            )
            db.commit()
            return operation.id

    with ThreadPoolExecutor(max_workers=2) as pool:
        identities = list(pool.map(lambda _: create(), range(2)))
    assert identities[0] == identities[1]
    with import_setup.factory() as db:
        assert db.scalar(select(func.count()).select_from(ImportOperation)) == 1
