from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from sqlalchemy import select
from tests.support.imports.data import NOW, ImportSetup, create_batch

from backend_app.models.imports import ImportBatch, ImportBatchEvent, ImportTask
from backend_app.repositories.imports.tasks import claim_tasks, ensure_task


def _task(setup: ImportSetup, batch_id: str) -> None:
    with setup.factory() as db:
        ensure_task(
            db,
            "precheck",
            batch_id,
            now=NOW,
            checkpoint={"schema_version": 1, "target_preview_version": 1, "next_row_no": 2},
        )
        db.commit()


def test_claim_and_takeover_events_commit_atomically_with_lease_generation(
    import_setup: ImportSetup,
) -> None:
    batch_id = create_batch(import_setup)
    _task(import_setup, batch_id)
    with import_setup.factory() as db:
        assert claim_tasks(db, now=NOW)
        db.rollback()
    with import_setup.factory() as db:
        assert list(db.scalars(select(ImportBatchEvent))) == []
        task = db.scalars(select(ImportTask)).one()
        assert task.attempt_count == 0 and task.status == "ready"
        first = claim_tasks(db, now=NOW)[0]
        db.commit()
    with import_setup.factory() as db:
        current = claim_tasks(db, now=NOW + timedelta(seconds=31))[0]
        db.commit()
    assert first.id == current.id and current.attempt_count == 2
    with import_setup.factory() as db:
        assert claim_tasks(db, now=NOW + timedelta(seconds=32)) == ()
        db.commit()
        events = list(db.scalars(select(ImportBatchEvent).order_by(ImportBatchEvent.sequence_no)))
        assert [event.event_type for event in events] == ["task_claimed", "task_taken_over"]
        assert [event.sequence_no for event in events] == [1, 2]
        assert [event.task_attempt for event in events] == [1, 2]
        assert all(event.task_id == first.id for event in events)
        assert all(set(event.safe_metadata) == {"phase", "attempt_count"} for event in events)


def test_claim_skips_busy_batch_before_locking_task_so_worker_lock_order_cannot_deadlock(
    import_setup: ImportSetup,
) -> None:
    batch_id = create_batch(import_setup)
    _task(import_setup, batch_id)

    def claim() -> tuple[str, ...]:
        with import_setup.factory() as db:
            leases = claim_tasks(db, now=NOW)
            db.commit()
            return tuple(lease.id for lease in leases)

    with import_setup.factory() as worker_db:
        worker_db.scalars(
            select(ImportBatch).where(ImportBatch.id == batch_id).with_for_update()
        ).one()
        # The worker owns the batch and will next lock its task. A claimant must skip
        # this batch immediately, instead of retaining the task while waiting for it.
        with ThreadPoolExecutor(max_workers=1) as workers:
            result = workers.submit(claim)
            assert result.result(timeout=2) == ()
        task = worker_db.scalars(
            select(ImportTask).where(ImportTask.batch_id == batch_id).with_for_update()
        ).one()
        assert task.status == "ready" and task.attempt_count == 0
        worker_db.rollback()
    assert len(claim()) == 1


def test_claim_skips_locked_task_without_waiting_and_can_claim_another_batch(
    import_setup: ImportSetup,
) -> None:
    first, second = create_batch(import_setup), create_batch(import_setup)
    _task(import_setup, first)
    _task(import_setup, second)
    with import_setup.factory() as owner:
        owner.scalars(select(ImportBatch).where(ImportBatch.id == first).with_for_update()).one()
        with import_setup.factory() as claimant:
            leases = claim_tasks(claimant, now=NOW, limit=1)
            assert len(leases) == 1 and leases[0].batch_id == second
            claimant.commit()
        owner.rollback()
    with import_setup.factory() as owner:
        task = owner.scalars(
            select(ImportTask).where(ImportTask.batch_id == first).with_for_update()
        ).one()
        with import_setup.factory() as claimant:
            assert claim_tasks(claimant, now=NOW, limit=1) == ()
            claimant.rollback()
        assert task.status == "ready"
