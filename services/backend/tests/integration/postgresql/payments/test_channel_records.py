from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker
from tests.support.payment_tasks import reconciliation_run

from backend_app.integrations.wechatpay.client import ChannelResponse, WechatPayError
from backend_app.models.payments import (
    PaymentChannelNotification,
    PaymentChannelRequest,
    PaymentReconciliationRun,
    PaymentTask,
)
from backend_app.repositories.payments.channel_records import (
    finish_statement,
    save_response,
    start_request,
    store_notification,
)
from backend_app.repositories.payments.tasks import (
    LeaseLost,
    claim_tasks,
    complete_task,
    ensure_task,
    require_current_lease,
)
from backend_app.services.worker.payments.execution import (
    RecordedChannelError,
    perform_channel_call,
)

NOW = datetime(2026, 10, 19, 4, tzinfo=UTC)


def test_notification_and_unique_processing_job_commit_together(
    payment_task_factory: sessionmaker[Session],
) -> None:
    factory = payment_task_factory
    with factory() as db:
        first, created = store_notification(
            db,
            channel_notification_id="notification1",
            notification_type="payment_success",
            payload={"order_no": "PAY1"},
            now=NOW,
        )
        notice_id = first.id
        assert created
        db.commit()
    with factory() as db:
        replay, created = store_notification(
            db,
            channel_notification_id="notification1",
            notification_type="payment_success",
            payload={"order_no": "PAY1"},
            now=NOW,
        )
        assert replay.id == notice_id and not created
        assert db.scalar(select(func.count()).select_from(PaymentTask)) == 1
        db.commit()
    with factory() as db:
        store_notification(
            db,
            channel_notification_id="rolled-back",
            notification_type="payment_success",
            payload={"order_no": "PAY2"},
            now=NOW,
        )
        db.rollback()
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(PaymentChannelNotification)) == 1
        assert db.scalar(select(func.count()).select_from(PaymentTask)) == 1


def test_duplicate_notification_with_changed_facts_does_not_replace_evidence(
    payment_task_factory: sessionmaker[Session],
) -> None:
    factory = payment_task_factory
    with factory() as db:
        store_notification(
            db,
            channel_notification_id="notification1",
            notification_type="payment_success",
            payload={"order_no": "PAY1"},
            now=NOW,
        )
        db.commit()
    with factory() as db, pytest.raises(ValueError, match="conflicts"):
        store_notification(
            db,
            channel_notification_id="notification1",
            notification_type="payment_success",
            payload={"order_no": "PAY2"},
            now=NOW,
        )
    with factory() as db:
        assert db.scalars(select(PaymentChannelNotification)).one().payload == {"order_no": "PAY1"}


def test_network_call_has_no_open_transaction_and_success_survives_business_rollback(
    payment_task_factory: sessionmaker[Session],
) -> None:
    factory = payment_task_factory
    run_id = reconciliation_run(factory, now=NOW)

    def call() -> ChannelResponse[dict[str, str]]:
        # Started evidence is committed and unlocked before the network boundary.
        with factory() as db:
            attempt = db.scalars(select(PaymentChannelRequest).with_for_update(nowait=True)).one()
            assert attempt.outcome == "started" and attempt.finished_at is None
            db.rollback()
        return ChannelResponse({"source_digest": "1" * 40}, 200, "channel-request-1")

    result = perform_channel_call(
        factory,
        operation="platform_fundflow_statement",
        target_id=run_id,
        request_snapshot={"business_date": "2026-10-19"},
        diagnostic_request_id="request1",
        call=call,
        snapshot=lambda value: value,
        clock=lambda: NOW,
    )
    with factory() as db:
        run = db.get(PaymentReconciliationRun, run_id)
        assert run is not None
        run.status = "failed"
        db.rollback()
    with factory() as db:
        attempt = db.get(PaymentChannelRequest, result.request_record_id)
        assert attempt is not None and attempt.outcome == "verified_response"
        assert attempt.finished_at == NOW
        assert attempt.response_snapshot == {"source_digest": "1" * 40}
        run = db.get(PaymentReconciliationRun, run_id)
        assert run is not None and run.status == "ready"


def test_transport_unknown_is_saved_with_original_business_target(
    payment_task_factory: sessionmaker[Session],
) -> None:
    factory = payment_task_factory
    run_id = reconciliation_run(factory, now=NOW)

    def call() -> ChannelResponse[dict[str, str]]:
        raise WechatPayError("TRANSPORT_UNKNOWN", outcome="transport_unknown")

    with pytest.raises(RecordedChannelError) as caught:
        perform_channel_call(
            factory,
            operation="platform_fundflow_statement",
            target_id=run_id,
            request_snapshot={},
            diagnostic_request_id="request1",
            call=call,
            snapshot=lambda value: value,
            clock=lambda: NOW,
        )
    with factory() as db:
        attempt = db.get(PaymentChannelRequest, caught.value.request_record_id)
        assert attempt is not None and attempt.outcome == "transport_unknown"
        assert attempt.reconciliation_run_id == run_id
        assert attempt.error_code == "TRANSPORT_UNKNOWN"


def test_late_authenticated_evidence_is_saved_but_old_worker_cannot_apply_it(
    payment_task_factory: sessionmaker[Session],
) -> None:
    factory = payment_task_factory
    run_id = reconciliation_run(factory, now=NOW)
    with factory() as db:
        ensure_task(db, "reconciliation", run_id, now=NOW)
        old = claim_tasks(db, now=NOW, task_types={"reconciliation"})[0]
        db.commit()

    def call() -> ChannelResponse[dict[str, str]]:
        with factory() as db:
            new = claim_tasks(db, now=NOW + timedelta(seconds=31), task_types={"reconciliation"})[0]
            assert new.attempt_count == old.attempt_count + 1
            db.commit()
        return ChannelResponse({"source_digest": "1" * 40}, 200, "late-response")

    result = perform_channel_call(
        factory,
        operation="platform_fundflow_statement",
        target_id=run_id,
        request_snapshot={},
        diagnostic_request_id="request1",
        call=call,
        snapshot=lambda value: value,
        lease=old,
        clock=lambda: NOW,
    )
    with factory() as db:
        attempt = db.get(PaymentChannelRequest, result.request_record_id)
        assert attempt is not None and attempt.response_snapshot == {"source_digest": "1" * 40}
    with factory() as db, pytest.raises(LeaseLost):
        require_current_lease(db, old, now=NOW + timedelta(seconds=32))


def test_statement_source_precedes_atomic_decisions_and_rollback_preserves_it(
    payment_task_factory: sessionmaker[Session],
) -> None:
    factory = payment_task_factory
    run_id = reconciliation_run(factory, now=NOW)
    with factory() as db:
        ensure_task(db, "reconciliation", run_id, now=NOW)
        lease = claim_tasks(db, now=NOW, task_types={"reconciliation"})[0]
        attempt = start_request(
            db,
            operation="statement_download",
            target_id=run_id,
            request_snapshot={},
            request_id="request1",
            now=NOW,
        )
        attempt_id = attempt.id
        db.commit()
    with factory() as db:
        save_response(
            db,
            attempt_id,
            outcome="verified_response",
            now=NOW,
            response_snapshot={"source_digest": "1" * 40},
            seal=False,
        )
        db.commit()
    with factory() as db:
        finish_statement(db, attempt_id, lease, now=NOW, decision_snapshot={"decisions": []})
        complete_task(db, lease, now=NOW)
        db.rollback()
    with factory() as db:
        unfinished = db.get(PaymentChannelRequest, attempt_id)
        assert unfinished is not None and unfinished.finished_at is None
        assert unfinished.response_snapshot == {"source_digest": "1" * 40}
        finish_statement(db, attempt_id, lease, now=NOW, decision_snapshot={"decisions": []})
        complete_task(db, lease, now=NOW)
        db.commit()
    with factory() as db:
        finished = db.get(PaymentChannelRequest, attempt_id)
        assert finished is not None and finished.finished_at == NOW
        assert finished.response_snapshot == {"source_digest": "1" * 40, "decisions": []}


def test_authenticated_source_cannot_be_changed_when_adding_decisions(
    payment_task_factory: sessionmaker[Session],
) -> None:
    factory = payment_task_factory
    run_id = reconciliation_run(factory, now=NOW)
    with factory() as db:
        ensure_task(db, "reconciliation", run_id, now=NOW)
        lease = claim_tasks(db, now=NOW, task_types={"reconciliation"})[0]
        attempt = start_request(
            db,
            operation="statement_download",
            target_id=run_id,
            request_snapshot={},
            request_id="request1",
            now=NOW,
        )
        attempt_id = attempt.id
        db.commit()
    with factory() as db:
        save_response(
            db,
            attempt_id,
            outcome="verified_response",
            now=NOW,
            response_snapshot={"source_digest": "1" * 40},
            seal=False,
        )
        db.commit()
    with factory() as db, pytest.raises(ValueError, match="cannot be overwritten"):
        finish_statement(
            db, attempt_id, lease, now=NOW, decision_snapshot={"source_digest": "2" * 40}
        )
