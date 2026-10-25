from concurrent.futures import ThreadPoolExecutor
from time import monotonic
from typing import Any

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session
from tests.support.payment_api import PaymentHouse
from tests.support.payment_management import managed_scenario

from backend_app.domain.admin.audit import AdminAudit
from backend_app.models.admin import AdminAuditLog, AdminRole, utc_now
from backend_app.models.billing import Bill, BillOperation, BillSettlementEntry
from backend_app.models.payments import (
    BillPaymentReservation,
    PaymentOrder,
    PaymentReconciliationDiscrepancy,
    PaymentReconciliationRun,
    PaymentTask,
    PaymentUnfreezeOrder,
    ProfitSharingAllocation,
    ProfitSharingOrder,
    ProfitSharingOrderItem,
)
from backend_app.repositories.admin import AdminRepository
from backend_app.repositories.payments.tasks import ensure_task


def funds_snapshot(db: Session) -> list[list[tuple[Any, ...]]]:
    return [
        list(db.execute(select(model.__table__).order_by(*model.__table__.primary_key)).tuples())
        for model in (
            PaymentOrder,
            Bill,
            BillOperation,
            BillSettlementEntry,
            BillPaymentReservation,
            ProfitSharingAllocation,
            ProfitSharingOrder,
            ProfitSharingOrderItem,
            PaymentUnfreezeOrder,
        )
    ]


def test_payment_recovery_requires_csrf_and_merges_original_task_with_audit(
    payment_house: PaymentHouse,
) -> None:
    house = payment_house
    scenario = managed_scenario(house, complete=False)
    harness = house.workspace.platform
    client = harness.client
    path = f"/v1/payment-orders/{scenario.payment.order_id}"
    before = client.get(path)
    body = {"reason": "隔离测试恢复原任务", "expected_state_token": before.json()["state_token"]}
    assert client.post(path + "/recoveries", json=body).status_code == 403
    for _ in range(2):
        accepted = client.post(path + "/recoveries", json=body, headers=harness.headers())
        assert accepted.status_code == 202, accepted.text
        assert accepted.headers["Cache-Control"] == "no-store"
        assert accepted.json()["target_id"] == scenario.payment.order_id
    assert client.get(path).json() == before.json()
    with harness.factory() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(PaymentTask)
                .where(
                    PaymentTask.payment_order_id == scenario.payment.order_id,
                    PaymentTask.task_type == "payment_submit",
                )
            )
            == 1
        )
        audits = db.scalars(
            select(AdminAuditLog).where(AdminAuditLog.action == "payment.payment_order.recover")
        ).all()
        assert len(audits) == 2
        assert all(item.safe_metadata["reason"] == body["reason"] for item in audits)
        assert db.get(PaymentOrder, scenario.payment.order_id).status == "pending"  # type: ignore[union-attr]
    stale = client.post(
        path + "/recoveries",
        json={**body, "expected_state_token": "stale"},
        headers=harness.headers(),
    )
    assert stale.status_code == 409 and stale.json()["code"] == "resource.conflict"


def test_difference_recovery_schedules_original_business_and_recheck(
    payment_house: PaymentHouse,
) -> None:
    house = payment_house
    scenario = managed_scenario(house, complete=False)
    harness = house.workspace.platform
    path = f"/v1/payment-reconciliation-discrepancies/{scenario.linked_difference_id}"
    token = harness.client.get(path).json()["state_token"]
    response = harness.client.post(
        path + "/recoveries",
        json={"reason": "核查原支付", "expected_state_token": token},
        headers=harness.headers(),
    )
    assert response.status_code == 202, response.text
    after = harness.client.get(path).json()
    assert after["status"] == "observing" and after["payment_order_id"] == scenario.payment.order_id
    with harness.factory() as db:
        assert db.get(PaymentOrder, scenario.payment.order_id).status == "pending"  # type: ignore[union-attr]
        task = db.scalars(
            select(PaymentTask).where(PaymentTask.reconciliation_run_id == scenario.run_id)
        ).one()
        assert task.task_type == "reconciliation" and task.status == "ready"
    unlinked_path = f"/v1/payment-reconciliation-discrepancies/{scenario.unlinked_difference_id}"
    unlinked = harness.client.get(unlinked_path).json()
    refused = harness.client.post(
        unlinked_path + "/recoveries",
        json={"reason": "不得猜测关联", "expected_state_token": unlinked["state_token"]},
        headers=harness.headers(),
    )
    assert refused.status_code == 409 and refused.json()["code"] == "payment.recovery_not_allowed"


def test_funds_recovery_reactivates_original_sharing_without_new_execution(
    payment_house: PaymentHouse,
) -> None:
    house = payment_house
    scenario = managed_scenario(house)
    harness = house.workspace.platform
    with harness.factory() as db:
        sharing = db.scalars(select(ProfitSharingOrder)).one()
        sharing_id = sharing.id
        task = db.scalars(
            select(PaymentTask).where(PaymentTask.profit_sharing_order_id == sharing_id)
        ).one()
        task.status, task.last_error = "paused", "ISOLATED_CONFIGURATION"
        task_id = task.id
        db.commit()
    path = f"/v1/payment-orders/{scenario.payment.order_id}"
    before = harness.client.get(path).json()
    accepted = harness.client.post(
        path + "/recoveries",
        json={"reason": "恢复原分账任务", "expected_state_token": before["state_token"]},
        headers=harness.headers(),
    )
    assert accepted.status_code == 202, accepted.text
    with harness.factory() as db:
        sharings = db.scalars(select(ProfitSharingOrder)).all()
        assert len(sharings) == 1 and sharings[0].id == sharing_id
        restored = db.get(PaymentTask, task_id)
        assert restored and restored.status == "ready"
        assert sharings[0].status == "pending"


def test_recheck_reschedules_original_batch_with_reason_and_rejects_stale_token(
    payment_house: PaymentHouse,
) -> None:
    house = payment_house
    scenario = managed_scenario(house)
    harness = house.workspace.platform
    path = f"/v1/payment-reconciliation-runs/{scenario.run_id}"
    before = harness.client.get(path).json()
    body = {"reason": "重新核对原批次", "expected_state_token": before["state_token"]}
    accepted = harness.client.post(path + "/rechecks", json=body, headers=harness.headers())
    assert accepted.status_code == 202, accepted.text
    after = harness.client.get(path).json()
    assert after["id"] == before["id"] and after["status"] == "ready"
    stale = harness.client.post(path + "/rechecks", json=body, headers=harness.headers())
    assert stale.status_code == 409 and stale.json()["code"] == "resource.conflict"
    with harness.factory() as db:
        tasks = db.scalars(
            select(PaymentTask).where(PaymentTask.reconciliation_run_id == scenario.run_id)
        ).all()
        assert len(tasks) == 1 and tasks[0].task_type == "reconciliation"
        audit = db.scalars(
            select(AdminAuditLog).where(
                AdminAuditLog.action == "payment.reconciliation_run.recover"
            )
        ).one()
        assert audit.safe_metadata["reason"] == body["reason"]


def test_external_resolution_records_audit_without_mutating_any_funds(
    payment_house: PaymentHouse,
) -> None:
    house = payment_house
    scenario = managed_scenario(house)
    harness = house.workspace.platform
    path = f"/v1/payment-reconciliation-discrepancies/{scenario.unlinked_difference_id}"
    before = harness.client.get(path).json()
    with harness.factory() as db:
        funds_before = funds_snapshot(db)
        tasks_before = list(
            db.execute(select(PaymentTask.__table__).order_by(PaymentTask.id)).tuples()
        )
    body = {
        "reason": "已完成独立外部凭据核查",
        "evidence_reference": "isolated-case-reference",
        "expected_state_token": before["state_token"],
    }
    response = harness.client.post(
        path + "/external-resolutions", json=body, headers=harness.headers()
    )
    assert response.status_code == 200, response.text
    after = response.json()
    assert after["status"] == "resolved" and after["payment_order_id"] is None
    assert after["evidence"] == before["evidence"]
    assert body["reason"] not in response.text and body["evidence_reference"] not in response.text
    with harness.factory() as db:
        assert funds_snapshot(db) == funds_before
        assert (
            list(db.execute(select(PaymentTask.__table__).order_by(PaymentTask.id)).tuples())
            == tasks_before
        )
        audit = db.scalars(
            select(AdminAuditLog).where(
                AdminAuditLog.action == "payment.reconciliation_discrepancy.external_resolution"
            )
        ).one()
        assert audit.safe_metadata["reason"] == body["reason"]
        assert audit.safe_metadata["evidence_reference"] == body["evidence_reference"]
        assert audit.safe_metadata["before"]["status"] == "open"
    replay = harness.client.post(
        path + "/external-resolutions", json=body, headers=harness.headers()
    )
    assert replay.status_code == 409 and harness.client.get(path).json() == after


def test_external_resolution_and_audit_roll_back_together(
    payment_house: PaymentHouse, monkeypatch: pytest.MonkeyPatch
) -> None:
    house = payment_house
    scenario = managed_scenario(house)
    harness = house.workspace.platform
    path = f"/v1/payment-reconciliation-discrepancies/{scenario.unlinked_difference_id}"
    before = harness.client.get(path).json()

    def fail_audit(self: AdminAudit, **values: Any) -> None:
        raise RuntimeError("isolated audit failure")

    monkeypatch.setattr(AdminAudit, "record", fail_audit)
    failed = harness.client.post(
        path + "/external-resolutions",
        json={
            "reason": "原子性验证",
            "evidence_reference": "isolated",
            "expected_state_token": before["state_token"],
        },
        headers=harness.headers(),
    )
    assert failed.status_code == 500
    assert harness.client.get(path).json() == before
    with harness.factory() as db:
        item = db.get(PaymentReconciliationDiscrepancy, scenario.unlinked_difference_id)
        assert item and item.status == "open" and item.resolved_at is None


def test_normally_recoverable_difference_rejects_external_resolution(
    payment_house: PaymentHouse,
) -> None:
    house = payment_house
    scenario = managed_scenario(house, complete=False)
    harness = house.workspace.platform
    path = f"/v1/payment-reconciliation-discrepancies/{scenario.linked_difference_id}"
    before = harness.client.get(path).json()
    response = harness.client.post(
        path + "/external-resolutions",
        json={
            "reason": "应先恢复原流程",
            "evidence_reference": "isolated",
            "expected_state_token": before["state_token"],
        },
        headers=harness.headers(),
    )
    assert response.status_code == 409 and response.json()["code"] == "payment.recovery_not_allowed"
    assert harness.client.get(path).json() == before


@pytest.mark.parametrize(
    "permissions",
    [
        {"platform.payment_reconciliation.read"},
        {"platform.payment.read"},
    ],
)
def test_external_resolution_requires_funds_exception_processing(
    payment_house: PaymentHouse, permissions: set[str]
) -> None:
    house = payment_house
    scenario = managed_scenario(house)
    harness = house.workspace.platform
    path = f"/v1/payment-reconciliation-discrepancies/{scenario.unlinked_difference_id}"
    token = harness.client.get(path).json()["state_token"]
    account_id = harness.client.get("/v1/admin-accounts/me").json()["id"]
    with harness.factory() as db:
        role = AdminRole(
            scope="platform_admin", code="limited_external", name="受限处置", is_system=False
        )
        db.add(role)
        db.flush()
        repo = AdminRepository(db, "platform_admin")
        repo.replace_permissions(role.id, permissions)
        repo.replace_roles(account_id, {role.id})
        db.commit()
    denied = harness.client.post(
        path + "/external-resolutions",
        json={
            "reason": "权限验证",
            "evidence_reference": "isolated",
            "expected_state_token": token,
        },
        headers=harness.headers(),
    )
    assert denied.status_code == 403 and denied.json()["code"] == "auth.forbidden"


def test_external_resolution_rechecks_batch_after_waiting_for_reconciliation(
    payment_house: PaymentHouse,
) -> None:
    house = payment_house
    scenario = managed_scenario(house)
    harness = house.workspace.platform
    path = f"/v1/payment-reconciliation-discrepancies/{scenario.unlinked_difference_id}"
    before = harness.client.get(path).json()
    headers = harness.headers()
    with harness.factory() as blocker, ThreadPoolExecutor(max_workers=1) as pool:
        run = blocker.scalar(
            select(PaymentReconciliationRun)
            .where(PaymentReconciliationRun.id == scenario.run_id)
            .with_for_update()
        )
        assert run
        pid = blocker.scalar(text("SELECT pg_backend_pid()"))
        future = pool.submit(
            harness.client.post,
            path + "/external-resolutions",
            json={
                "reason": "竞争核验",
                "evidence_reference": "isolated",
                "expected_state_token": before["state_token"],
            },
            headers=headers,
        )
        try:
            with harness.factory() as observer:
                deadline = monotonic() + 5
                while not observer.scalar(
                    text(
                        "SELECT EXISTS (SELECT 1 FROM pg_stat_activity "
                        "WHERE :pid = ANY(pg_blocking_pids(pid)))"
                    ),
                    {"pid": pid},
                ):
                    assert monotonic() < deadline, "Resolution never waited for batch lock"
                    if future.done():
                        future.result()
                    observer.execute(text("SELECT pg_stat_clear_snapshot()"))
            run.status, run.finished_at = "running", None
            run.updated_at = utc_now()
            ensure_task(blocker, "reconciliation", run.id, now=utc_now())
            blocker.commit()
        finally:
            blocker.rollback()
        rejected = future.result(timeout=10)
        assert rejected.status_code == 409 and rejected.json()["code"] == "resource.conflict"
    assert harness.client.get(path).json()["status"] == "open"
