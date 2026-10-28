from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from typing import Any

import pytest
from pytest import MonkeyPatch
from sqlalchemy import Connection, event, func, select
from sqlalchemy.orm import Mapper, Session
from tests.support.housing import create_house, housing_path, set_permissions
from tests.support.imports.fee_bases import BasisImports, basis_row
from tests.support.workspace import PREFIX, WorkspaceHarness

from backend_app.domain.imports.errors import ImportExecutionFailure, ImportOutcomeUnknown
from backend_app.domain.imports.types import ImportContext, ImportPlan
from backend_app.models.admin import AdminAuditLog, utc_now
from backend_app.models.billing import Bill, FeeBasisVersion
from backend_app.models.imports import ImportOperation, ImportRow
from backend_app.repositories.imports.tasks import claim_tasks
from backend_app.services.worker.imports.adapters.fee_bases import FeeBasisImportAdapter


@pytest.fixture
def basis_imports(workspace: WorkspaceHarness) -> BasisImports:
    return BasisImports.for_workspace(workspace)


@pytest.mark.parametrize("extension", ["csv", "xlsx"])
def test_preview_is_read_only_and_execution_creates_one_version_and_audit(
    basis_imports: BasisImports, extension: str
) -> None:
    h = basis_imports
    house = h.house()
    batch_id = h.upload([basis_row()], extension)
    preview = h.get(batch_id)
    assert preview["status"] == "preview_ready", preview
    assert preview["statistics"]["preview"]["create_rows"] == 1
    assert preview["business_preview"]["summary"] == []
    row = h.get(batch_id, "/rows")["items"][0]
    assert "_prepared" not in str(row) and "house_snapshot" not in str(row)
    assert "01栋" in str(row["business_values"])
    assert h.count() == 0
    completed = h.execute(batch_id)
    assert completed["status"] == "completed", completed
    assert completed["statistics"]["execution"]["created_rows"] == 1
    with h.workspace.platform.factory() as db:
        basis = db.scalars(select(FeeBasisVersion)).one()
        operation = db.scalars(select(ImportOperation)).one()
        audit = db.scalars(
            select(AdminAuditLog).where(AdminAuditLog.action == "property.fee_basis.create")
        ).one()
        assert basis.house_id == house["id"] and basis.version_no == 1
        assert basis.unit_price_cents == 200 and str(basis.area_sqm) == "100.0000"
        assert operation.target_id == audit.target_id == basis.id
        assert db.scalar(select(func.count()).select_from(Bill)) == 0


def test_equivalent_area_and_changed_reason_skip_without_overwriting_history(
    basis_imports: BasisImports,
) -> None:
    h = basis_imports
    house = h.house()
    original = h.manual_basis(house["id"])
    batch_id = h.upload([basis_row(area_sqm="100.0000", change_reason="另一个说明")])
    assert h.get(batch_id)["statistics"]["preview"]["skip_rows"] == 1
    assert h.execute(batch_id)["statistics"]["execution"]["skipped_rows"] == 1
    with h.workspace.platform.factory() as db:
        basis = db.scalars(select(FeeBasisVersion)).one()
        assert basis.id == original["id"] and basis.change_reason == "初次设置"
        assert (
            db.scalar(
                select(func.count())
                .select_from(AdminAuditLog)
                .where(AdminAuditLog.action == "property.fee_basis.create")
            )
            == 1
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"house_usage": "商业"},
        {"area_sqm": "200", "unit_price_amount": "1"},
        {"fixed_amount": "200"},
        {"unit_price_amount": "2.01"},
    ],
)
def test_business_field_changes_append_even_when_calculated_amount_is_equal(
    basis_imports: BasisImports, changes: dict[str, Any]
) -> None:
    h = basis_imports
    h.manual_basis(h.house()["id"])
    batch_id = h.upload([basis_row(**changes)])
    assert h.execute(batch_id)["statistics"]["execution"]["created_rows"] == 1
    assert h.count() == 2


def test_fixed_zero_preserves_and_compares_optional_parameters(basis_imports: BasisImports) -> None:
    h = basis_imports
    h.manual_basis(h.house()["id"], fixed_amount_cents=0)
    skipped = h.upload([basis_row(fixed_amount="0")])
    assert h.execute(skipped)["statistics"]["execution"]["skipped_rows"] == 1
    changed = h.upload([basis_row(fixed_amount="0", area_sqm="101")])
    assert h.execute(changed)["statistics"]["execution"]["created_rows"] == 1
    assert h.count() == 2


def test_new_batches_allow_a_b_a_and_repeated_a_does_not_append(
    basis_imports: BasisImports,
) -> None:
    h = basis_imports
    h.house()
    batches = [h.upload([basis_row()])]
    assert h.execute(batches[-1])["statistics"]["execution"]["created_rows"] == 1
    for price in ["3", "2"]:
        batches.append(h.upload([basis_row(unit_price_amount=price)]))
        assert h.execute(batches[-1])["statistics"]["execution"]["created_rows"] == 1
    repeated = h.upload([basis_row()])
    assert h.execute(repeated)["statistics"]["execution"]["skipped_rows"] == 1
    with h.workspace.platform.factory() as db:
        versions = db.scalars(select(FeeBasisVersion).order_by(FeeBasisVersion.version_no)).all()
        assert [(b.version_no, b.unit_price_cents) for b in versions] == [
            (1, 200),
            (2, 300),
            (3, 200),
        ]
        assert h.get(batches[0])["statistics"]["execution"]["created_rows"] == 1


def test_new_month_keeps_boundary_future_nodes_and_existing_bill(
    basis_imports: BasisImports,
) -> None:
    h = basis_imports
    house = h.house()
    original = h.manual_basis(house["id"])
    h.manual_basis(house["id"], effective_from_month="2026-07", unit_price_cents=400)
    created_bill = h.workspace.client.post(
        housing_path(h.workspace, "/bills"),
        json={
            "house_id": house["id"],
            "billing_month": "2026-03",
            "amount_source": "basis",
            "basis_version_id": original["id"],
            "expected_calculation_rule_version": 1,
            "expected_receivable_cents": 20000,
        },
        headers={**h.workspace.headers(), "Idempotency-Key": "historical-bill"},
    )
    assert created_bill.status_code == 201, created_bill.text
    before = created_bill.json()["bill"]
    for month, price in [("2026-04", "2"), ("2026-03", "3")]:
        batch_id = h.upload([basis_row(effective_from_month=month, unit_price_amount=price)])
        assert h.execute(batch_id)["statistics"]["execution"]["created_rows"] == 1
    for month, amount in [
        ("2026-02", 20000),
        ("2026-03", 30000),
        ("2026-04", 20000),
        ("2026-08", 40000),
    ]:
        calculation = h.workspace.client.post(
            housing_path(h.workspace, f"/houses/{house['id']}/property-fee-calculations"),
            json={"billing_month": month},
            headers=h.workspace.headers(),
        )
        assert calculation.status_code == 200, calculation.text
        assert calculation.json()["receivable_cents"] == amount
    with h.workspace.platform.factory() as db:
        bill = db.get(Bill, before["id"])
        assert bill and bill.receivable_cents == 20000 and bill.basis_version_id == original["id"]


@pytest.mark.parametrize("different_month,invalid", [(False, False), (True, False), (True, True)])
def test_all_duplicate_house_rows_are_rejected(
    basis_imports: BasisImports, different_month: bool, invalid: bool
) -> None:
    h = basis_imports
    h.house()
    batch_id = h.upload(
        [
            basis_row(),
            basis_row(
                effective_from_month="2026-02" if different_month else "2026-01",
                change_reason="" if invalid else "说明",
            ),
        ]
    )
    assert h.get(batch_id)["statistics"]["preview"]["error_rows"] == 2
    duplicates = {
        issue["row_no"]
        for issue in h.get(batch_id, "/issues")["items"]
        if issue["code"] == "import.duplicate_in_file"
    }
    assert duplicates == {2, 3}
    assert h.count() == 0


@pytest.mark.parametrize(
    "changes",
    [
        {"room_no": "9999"},
        {"house_external_code": "OTHER"},
        {"area_sqm": "0"},
        {"area_sqm": "1.00001"},
        {"area_sqm": ""},
        {"unit_price_amount": "-1"},
        {"unit_price_amount": "2.001"},
        {"fixed_amount": "90071992547409.92"},
        {"effective_from_month": "2026-13"},
        {"house_usage": "residential"},
        {"change_reason": " "},
    ],
)
def test_invalid_input_never_writes_even_when_content_might_match(
    basis_imports: BasisImports, changes: dict[str, Any]
) -> None:
    h = basis_imports
    h.manual_basis(h.house()["id"])
    batch_id = h.upload([basis_row(**changes)])
    assert h.get(batch_id)["statistics"]["preview"]["error_rows"] == 1
    assert h.count() == 1


@pytest.mark.parametrize("change", ["version", "room", "disabled"])
def test_execution_does_not_replace_confirmed_baseline_or_house(
    basis_imports: BasisImports, change: str
) -> None:
    h = basis_imports
    house = h.house()
    batch_id = h.upload([basis_row()])
    h.confirm(batch_id)
    if change == "version":
        h.manual_basis(house["id"], unit_price_cents=300)
    else:
        response = h.workspace.client.patch(
            housing_path(h.workspace, f"/houses/{house['id']}"),
            json={"room_no": "0002"} if change == "room" else {"enabled": False},
            headers=h.workspace.headers(),
        )
        assert response.status_code == 200, response.text
        if change == "room":
            create_house(h.workspace, house["space_node_id"], "0001", external_code="0001A")
    count = h.count()
    h.drain()
    result = h.get(batch_id)
    assert result["statistics"]["execution"]["failed_rows"] == 1, result
    assert "retry_failed" not in result["next_actions"]
    assert h.count() == count


def test_shared_success_replays_original_version_after_later_price_change(
    basis_imports: BasisImports,
) -> None:
    h = basis_imports
    house = h.house()
    first, overlap = h.upload([basis_row()]), h.upload([basis_row()])
    h.confirm(first)
    h.confirm(overlap)
    with h.workspace.platform.factory() as db:
        leases = claim_tasks(db, now=utc_now(), phases=("apply",))
        db.commit()
    assert len(leases) == 1 and leases[0].batch_id == first
    h.worker.run(leases[0])
    with h.workspace.platform.factory() as db:
        operation = db.scalars(select(ImportOperation)).one()
        original_id = operation.target_id
    assert h.get(first)["statistics"]["execution"]["created_rows"] == 1
    h.manual_basis(house["id"], unit_price_cents=300)
    h.drain()
    assert h.get(overlap)["statistics"]["execution"]["skipped_rows"] == 1
    with h.workspace.platform.factory() as db:
        original = db.get(FeeBasisVersion, original_id)
        assert original and original.version_no == 1 and h.count() == 2


def test_audit_failure_rolls_back_entire_row_but_preserves_other_rows(
    basis_imports: BasisImports,
) -> None:
    h = basis_imports
    first = h.house()
    create_house(h.workspace, first["space_node_id"], "0002", external_code="0001A")
    batch_id = h.upload([basis_row(), basis_row(room_no="0002")])
    h.confirm(batch_id)
    rejected = False

    def reject(mapper: Mapper[AdminAuditLog], connection: Connection, audit: AdminAuditLog) -> None:
        nonlocal rejected
        if audit.action == "property.fee_basis.create" and not rejected:
            rejected = True
            raise ImportExecutionFailure("import.execution_failed")

    event.listen(AdminAuditLog, "before_insert", reject)
    try:
        h.drain()
    finally:
        event.remove(AdminAuditLog, "before_insert", reject)
    result = h.get(batch_id)
    assert rejected and result["status"] == "partial_failed", result
    assert h.count() == 1
    with h.workspace.platform.factory() as db:
        assert sorted(db.scalars(select(ImportOperation.status))) == ["failed", "succeeded"]
        assert sorted(db.scalars(select(ImportRow.execution_status))) == ["created", "failed"]


@pytest.mark.parametrize(
    "skip,change", [(False, False), (False, True), (True, False), (True, True)]
)
def test_unknown_result_requires_original_evidence_and_never_creates_replacement(
    basis_imports: BasisImports, monkeypatch: MonkeyPatch, skip: bool, change: bool
) -> None:
    h = basis_imports
    house = h.house()
    if skip:
        h.manual_basis(house["id"])
    batch_id = h.upload([basis_row()])
    h.confirm(batch_id)
    original_execute = FeeBasisImportAdapter.execute

    def unknown(
        self: FeeBasisImportAdapter, plan: ImportPlan, context: ImportContext, db: Session
    ) -> Mapping[str, Any]:
        original_execute(self, plan, context, db)
        raise ImportOutcomeUnknown

    with monkeypatch.context() as patch:
        patch.setattr(FeeBasisImportAdapter, "execute", unknown)
        h.drain()
    assert h.get(batch_id)["statistics"]["execution"]["uncertain_rows"] == 1
    with h.workspace.platform.factory() as db:
        key = db.scalars(select(ImportOperation.operation_key)).one()
    if change:
        h.manual_basis(house["id"], unit_price_cents=300 if skip else 200)
    before = h.count()
    h.resume(batch_id, "recover")
    h.drain()
    result = h.get(batch_id)
    assert result["status"] == ("completed" if skip and not change else "blocked"), result
    assert h.count() == before
    with h.workspace.platform.factory() as db:
        assert db.scalars(select(ImportOperation.operation_key)).one() == key


def test_fee_basis_permission_alone_can_import_and_bill_reader_cannot_process(
    basis_imports: BasisImports,
) -> None:
    h = basis_imports
    h.house()
    set_permissions(h.workspace, {"property.fee_basis.manage"})
    types = h.workspace.client.get(f"{PREFIX}/import-types")
    assert types.status_code == 200, types.text
    assert [item["key"] for item in types.json()["items"]] == [h.definition.key]
    batch_id = h.upload([basis_row()])
    assert h.execute(batch_id)["statistics"]["execution"]["created_rows"] == 1
    set_permissions(h.workspace, {"property.bill.read"})
    assert h.get(batch_id)["next_actions"] == []
    assert h.get(batch_id, "/rows")["total"] == 1
    denied = h.workspace.client.post(
        f"{PREFIX}/import-batches/{batch_id}/recover",
        json={"reason": "无权限"},
        headers={**h.workspace.headers(), "Idempotency-Key": "denied-recover"},
    )
    assert denied.status_code == 403, denied.text


@pytest.mark.parametrize("baseline_changed", [False, True])
def test_retry_keeps_original_baseline_and_original_batch_history(
    basis_imports: BasisImports, monkeypatch: MonkeyPatch, baseline_changed: bool
) -> None:
    h = basis_imports
    house = h.house()
    batch_id = h.upload([basis_row()])
    h.confirm(batch_id)

    def fail(*args: Any, **kwargs: Any) -> Mapping[str, Any]:
        raise ImportExecutionFailure("import.system_error", retryable=True)

    with monkeypatch.context() as patch:
        patch.setattr(FeeBasisImportAdapter, "execute", fail)
        h.drain()
    original = h.get(batch_id)
    assert original["statistics"]["execution"]["retryable_failed_rows"] == 1
    with h.workspace.platform.factory() as db:
        key = db.scalars(select(ImportOperation.operation_key)).one()
    if baseline_changed:
        h.manual_basis(house["id"], unit_price_cents=300)
    retry = h.resume(batch_id, "retry-failed")
    h.drain()
    child_id = retry["batch"]["batch_id"]
    child = h.get(child_id)
    assert child["statistics"]["preview"]["error_rows"] == int(baseline_changed), child
    if not baseline_changed:
        assert h.execute(child_id)["statistics"]["execution"]["created_rows"] == 1
    assert h.get(batch_id)["statistics"]["execution"]["failed_rows"] == 1
    assert h.get(batch_id)["statistics"]["execution"]["created_rows"] == 0
    with h.workspace.platform.factory() as db:
        assert db.scalars(select(ImportOperation.operation_key)).one() == key
    assert h.count() == 1


def test_revoked_maintenance_permission_blocks_execution_even_for_planned_skip(
    basis_imports: BasisImports,
) -> None:
    h = basis_imports
    h.manual_basis(h.house()["id"])
    batch_id = h.upload([basis_row()])
    h.confirm(batch_id)
    set_permissions(h.workspace, {"property.bill.read"})
    h.drain()
    result = h.get(batch_id)
    assert result["status"] == "blocked" and result["last_error_code"] == "auth.forbidden"
    assert h.count() == 1


def test_retry_preview_reuses_shared_success_before_checking_old_baseline(
    basis_imports: BasisImports, monkeypatch: MonkeyPatch
) -> None:
    h = basis_imports
    h.house()
    first, overlap = h.upload([basis_row()]), h.upload([basis_row()])
    h.confirm(first)

    def fail(*args: Any, **kwargs: Any) -> Mapping[str, Any]:
        raise ImportExecutionFailure("import.system_error", retryable=True)

    with monkeypatch.context() as patch:
        patch.setattr(FeeBasisImportAdapter, "execute", fail)
        h.drain()
    child_id = h.resume(first, "retry-failed")["batch"]["batch_id"]
    h.confirm(overlap)
    with h.workspace.platform.factory() as db:
        leases = claim_tasks(db, now=utc_now(), phases=("apply",))
        db.commit()
    assert len(leases) == 1 and leases[0].batch_id == overlap
    h.worker.run(leases[0])
    assert h.get(overlap)["statistics"]["execution"]["created_rows"] == 1
    h.drain()
    child = h.get(child_id)
    assert child["statistics"]["preview"]["error_rows"] == 0, child
    assert h.execute(child_id)["statistics"]["execution"]["skipped_rows"] == 1
    assert h.get(first)["statistics"]["execution"]["failed_rows"] == 1
    assert h.count() == 1
    with h.workspace.platform.factory() as db:
        assert db.scalar(select(func.count()).select_from(ImportOperation)) == 1


@pytest.mark.postgresql
@pytest.mark.parametrize("same_content", [True, False])
def test_simultaneous_workers_create_one_version_with_atomic_operation_result(
    basis_imports: BasisImports, monkeypatch: MonkeyPatch, same_content: bool
) -> None:
    h = basis_imports
    h.house()
    batches = [
        h.upload([basis_row()]),
        h.upload([basis_row(unit_price_amount="2" if same_content else "3")]),
    ]
    for batch in batches:
        h.confirm(batch)
    with h.workspace.platform.factory() as db:
        leases = claim_tasks(db, now=utc_now(), phases=("apply",), limit=2)
        db.commit()
    assert len(leases) == 2
    barrier = Barrier(2)
    original_execute = FeeBasisImportAdapter.execute

    def simultaneous(
        self: FeeBasisImportAdapter, plan: ImportPlan, context: ImportContext, db: Session
    ) -> Mapping[str, Any]:
        barrier.wait(timeout=10)
        return original_execute(self, plan, context, db)

    if not same_content:
        monkeypatch.setattr(FeeBasisImportAdapter, "execute", simultaneous)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(h.worker.run, lease) for lease in leases]
        for future in futures:
            future.result(timeout=20)
    results = [h.get(batch)["statistics"]["execution"] for batch in batches]
    assert sum(result["created_rows"] for result in results) == 1
    assert sum(result["skipped_rows"] for result in results) == int(same_content)
    assert sum(result["failed_rows"] for result in results) == int(not same_content)
    assert h.count() == 1
    with h.workspace.platform.factory() as db:
        assert db.scalar(select(func.count()).select_from(ImportOperation)) == (
            1 if same_content else 2
        )
