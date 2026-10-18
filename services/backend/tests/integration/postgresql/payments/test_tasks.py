from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker
from tests.support.payment_tasks import notification_task

from backend_app.models.payments import PaymentTask
from backend_app.repositories.payments.tasks import (
    LeaseLost,
    claim_tasks,
    complete_task,
    ensure_task,
    pause_task,
    renew_task,
    require_current_lease,
    reschedule_task,
)

NOW = datetime(2026, 10, 19, 4, tzinfo=UTC)


def test_unique_merge_keeps_running_generation_and_original_target(
    payment_task_factory: sessionmaker[Session],
) -> None:
    factory = payment_task_factory
    task_id = notification_task(factory, now=NOW)
    with factory() as db:
        original = db.get(PaymentTask, task_id)
        assert original is not None
        target_id = original.notification_id
        assert target_id is not None
        merged = ensure_task(
            db, "notification_process", target_id, now=NOW, next_run_at=NOW + timedelta(minutes=1)
        )
        assert merged.id == task_id and merged.next_run_at == NOW
        first = claim_tasks(db, now=NOW, task_types={"notification_process"})[0]
        db.commit()
    with factory() as db:
        merged = ensure_task(db, "notification_process", target_id, now=NOW, reactivate=True)
        assert merged.id == task_id and merged.status == "running"
        assert merged.attempt_count == first.attempt_count
        assert db.scalar(select(func.count()).select_from(PaymentTask)) == 1
        db.commit()


def test_skip_locked_claim_does_not_wait_for_another_worker(
    payment_task_factory: sessionmaker[Session],
) -> None:
    factory = payment_task_factory
    notification_task(factory, now=NOW, key="one")
    notification_task(factory, now=NOW, key="two")
    with factory() as first, factory() as second:
        first_lease = claim_tasks(first, now=NOW, task_types={"notification_process"})[0]
        second_lease = claim_tasks(second, now=NOW, task_types={"notification_process"})[0]
        assert first_lease.id != second_lease.id
        second.commit()
        first.commit()


def test_concurrent_workers_cannot_claim_the_same_generation(
    payment_task_factory: sessionmaker[Session],
) -> None:
    factory = payment_task_factory
    notification_task(factory, now=NOW)
    barrier = Barrier(2)

    def claim() -> tuple[str, ...]:
        with factory() as db:
            barrier.wait(timeout=5)
            leases = claim_tasks(db, now=NOW, task_types={"notification_process"})
            db.commit()
            return tuple(lease.id for lease in leases)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: claim(), range(2)))
    assert sum(len(result) for result in results) == 1


@pytest.mark.parametrize("operation", ["complete", "reschedule", "pause", "renew", "require"])
def test_expired_worker_cannot_override_takeover(
    payment_task_factory: sessionmaker[Session], operation: str
) -> None:
    factory = payment_task_factory
    notification_task(factory, now=NOW)
    with factory() as db:
        old = claim_tasks(db, now=NOW, task_types={"notification_process"}, lease_seconds=30)[0]
        db.commit()
    later = NOW + timedelta(seconds=31)
    with factory() as db:
        new = claim_tasks(db, now=later, task_types={"notification_process"}, lease_seconds=30)[0]
        db.commit()
    assert new.id == old.id and new.attempt_count == old.attempt_count + 1
    with factory() as db, pytest.raises(LeaseLost):
        if operation == "complete":
            complete_task(db, old, now=later)
        elif operation == "reschedule":
            reschedule_task(db, old, now=later, next_run_at=later)
        elif operation == "pause":
            pause_task(db, old, now=later, error_code="payment.configuration_invalid")
        elif operation == "renew":
            renew_task(db, old, now=later)
        else:
            require_current_lease(db, old, now=later)
    with factory() as db:
        current = require_current_lease(db, new, now=later)
        assert current.status == "running" and current.attempt_count == new.attempt_count


def test_renewal_prevents_takeover_at_original_expiry(
    payment_task_factory: sessionmaker[Session],
) -> None:
    factory = payment_task_factory
    notification_task(factory, now=NOW)
    with factory() as db:
        lease = claim_tasks(db, now=NOW, task_types={"notification_process"}, lease_seconds=30)[0]
        db.commit()
    with factory() as db:
        renew_task(db, lease, now=NOW + timedelta(seconds=20), lease_seconds=30)
        db.commit()
    with factory() as db:
        assert not claim_tasks(
            db, now=NOW + timedelta(seconds=31), task_types={"notification_process"}
        )
        complete_task(db, lease, now=NOW + timedelta(seconds=31))
        db.commit()


def test_paused_and_deferred_tasks_need_explicit_business_reactivation(
    payment_task_factory: sessionmaker[Session],
) -> None:
    factory = payment_task_factory
    notification_task(factory, now=NOW)
    with factory() as db:
        lease = claim_tasks(db, now=NOW, task_types={"notification_process"})[0]
        reschedule_task(
            db,
            lease,
            now=NOW,
            next_run_at=NOW + timedelta(minutes=1),
            error_code="FREQUENCY_LIMITED",
        )
        db.commit()
    with factory() as db:
        assert not claim_tasks(
            db, now=NOW + timedelta(seconds=59), task_types={"notification_process"}
        )
        lease = claim_tasks(
            db, now=NOW + timedelta(minutes=1), task_types={"notification_process"}
        )[0]
        pause_task(db, lease, now=NOW + timedelta(minutes=1), error_code="NO_AUTH")
        db.commit()
    with factory() as db:
        assert not claim_tasks(db, now=NOW + timedelta(days=1), task_types={"notification_process"})
        task = db.get(PaymentTask, lease.id)
        assert task is not None and task.notification_id is not None
        ensure_task(db, "notification_process", task.notification_id, now=NOW + timedelta(days=1))
        assert task.status == "paused"
        ensure_task(
            db,
            "notification_process",
            task.notification_id,
            now=NOW + timedelta(days=1),
            reactivate=True,
        )
        db.commit()
    with factory() as db:
        assert (
            len(claim_tasks(db, now=NOW + timedelta(days=1), task_types={"notification_process"}))
            == 1
        )


def test_unregistered_handler_leaves_job_unclaimed(
    payment_task_factory: sessionmaker[Session],
) -> None:
    factory = payment_task_factory
    task_id = notification_task(factory, now=NOW)
    with factory() as db:
        assert not claim_tasks(db, now=NOW, task_types={"payment_submit"})
        task = db.get(PaymentTask, task_id)
        assert task is not None and task.status == "ready" and task.attempt_count == 0
