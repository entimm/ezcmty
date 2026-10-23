from __future__ import annotations

import csv
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from io import BytesIO, StringIO
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from openpyxl import Workbook
from pytest import MonkeyPatch
from sqlalchemy import Connection, event, func, select
from sqlalchemy.orm import Mapper, Session
from tests.support.housing import create_house, create_node, housing_path, set_permissions
from tests.support.imports.pipeline import drain_worker
from tests.support.workspace import PREFIX, WorkspaceHarness

from backend_app.core.config import get_settings
from backend_app.domain.imports.errors import ImportExecutionFailure, ImportOutcomeUnknown
from backend_app.domain.imports.registry import ImportDefinition
from backend_app.domain.imports.types import ImportContext, ImportPlan
from backend_app.import_definitions.catalog import get_import_registry
from backend_app.models.admin import AdminAuditLog
from backend_app.models.billing import Bill, BillOperation, BillSettlementEntry
from backend_app.models.imports import ImportOperation, ImportRow
from backend_app.services.bill_creation import BillCreationResult, create_bill
from backend_app.services.worker.imports.adapters import bills as bill_adapter
from backend_app.services.worker.imports.pipeline import ImportWorkerService


@dataclass
class BillImports:
    workspace: WorkspaceHarness
    worker: ImportWorkerService
    definition: ImportDefinition

    def get(self, batch_id: str, suffix: str = "") -> dict[str, Any]:
        response = self.workspace.client.get(f"{PREFIX}/import-batches/{batch_id}{suffix}")
        assert response.status_code == 200, response.text
        return dict(response.json())

    def upload(self, rows: list[dict[str, Any]], extension: str = "csv") -> str:
        created = self.workspace.client.post(
            f"{PREFIX}/import-batches",
            json={
                "import_type": "property_fee_bills",
                "template_version_no": 1,
                "scope": {"type": "community", "id": self.workspace.community_id},
                "mode": "create",
            },
            headers={**self.workspace.headers(), "Idempotency-Key": uuid4().hex},
        )
        assert created.status_code == 201, created.text
        batch_id = str(created.json()["batch_id"])
        fields = sorted(self.definition.fields, key=lambda field: field.order)
        if extension == "csv":
            stream = StringIO()
            writer = csv.writer(stream)
            writer.writerow([field.label for field in fields])
            writer.writerows([[row.get(field.key, "") for field in fields] for row in rows])
            content = stream.getvalue().encode("utf-8-sig")
            media_type = "text/csv"
        else:
            workbook = Workbook()
            sheet = workbook.active
            assert sheet is not None
            sheet.title = self.definition.sheet_name
            sheet.append([field.label for field in fields])
            for row in rows:
                sheet.append([row.get(field.key, "") for field in fields])
            output = BytesIO()
            workbook.save(output)
            workbook.close()
            content = output.getvalue()
            media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        uploaded = self.workspace.client.post(
            f"{PREFIX}/import-batches/{batch_id}/source-file",
            files={"file": (f"bills.{extension}", content, media_type)},
            headers={**self.workspace.headers(), "Idempotency-Key": uuid4().hex},
        )
        assert uploaded.status_code == 202, uploaded.text
        drain_worker(self.workspace.platform.factory, self.worker)
        return batch_id

    def confirm(self, batch_id: str) -> None:
        batch = self.get(batch_id)
        assert batch["status"] == "preview_ready", batch
        response = self.workspace.client.post(
            f"{PREFIX}/import-batches/{batch_id}/confirm",
            json={
                "preview_version": batch["preview"]["version"],
                "preview_fingerprint": batch["preview"]["fingerprint"],
                "apply_policy": "all_rows",
                "include_warning_rows": False,
            },
            headers={**self.workspace.headers(), "Idempotency-Key": uuid4().hex},
        )
        assert response.status_code == 202, response.text

    def execute(self, batch_id: str) -> dict[str, Any]:
        self.confirm(batch_id)
        drain_worker(self.workspace.platform.factory, self.worker)
        return self.get(batch_id)

    def counts(self) -> dict[str, int]:
        with self.workspace.platform.factory() as db:
            return {
                "bills": int(db.scalar(select(func.count()).select_from(Bill)) or 0),
                "entries": int(
                    db.scalar(select(func.count()).select_from(BillSettlementEntry)) or 0
                ),
                "operations": int(db.scalar(select(func.count()).select_from(BillOperation)) or 0),
                "audits": int(
                    db.scalar(
                        select(func.count())
                        .select_from(AdminAuditLog)
                        .where(AdminAuditLog.action == "property.bill.create")
                    )
                    or 0
                ),
            }


@pytest.fixture
def bill_imports(
    workspace: WorkspaceHarness, monkeypatch: MonkeyPatch, tmp_path: Path
) -> BillImports:
    workspace.complete_login()
    monkeypatch.setenv("APP_IMPORT_STORAGE_ROOT", str(tmp_path / "private-imports"))
    get_settings.cache_clear()
    # Keep the deployed resource catalogue and adapter binding, including the API's registry.
    registry = get_import_registry()
    return BillImports(
        workspace,
        ImportWorkerService(workspace.platform.factory, get_settings()),
        registry.get("property_fee_bills", 1),
    )


def bill_row(**changes: Any) -> dict[str, Any]:
    return {
        "phase_name": "",
        "building_name": "01栋",
        "unit_name": "",
        "room_no": "001",
        "house_external_code": "",
        "billing_month": "2024-01",
        "receivable_amount": "100.00",
        "manual_amount_reason": "核对原始应收",
        "initial_paid_amount": "0.00",
        "initial_received_on": "",
        "initial_receipt_reason": "",
        "external_bill_no": "0001a",
        "due_date": "",
        **changes,
    }


def summary(batch: dict[str, Any]) -> dict[str, tuple[str, str]]:
    return {
        item["key"]: (item["without_warning_rows"], item["with_warning_rows"])
        for item in batch["business_preview"]["summary"]
    }


def create_manual(harness: BillImports, house_id: str, *, amount: int = 10000) -> dict[str, Any]:
    response = harness.workspace.client.post(
        housing_path(harness.workspace, "/bills"),
        json={
            "house_id": house_id,
            "billing_month": "2024-01",
            "amount_source": "manual",
            "receivable_cents": amount,
            "manual_amount_reason": "核对原始应收",
            "external_bill_no": "0001a",
        },
        headers={**harness.workspace.headers(), "Idempotency-Key": uuid4().hex},
    )
    assert response.status_code == 201, response.text
    return dict(response.json())


@pytest.mark.parametrize("extension", ["csv", "xlsx"])
def test_production_preview_and_atomic_creation_for_current_and_historical_bills(
    bill_imports: BillImports, extension: str
) -> None:
    workspace = bill_imports.workspace
    house = create_house(workspace, create_node(workspace, "01栋")["id"], "001")
    rows = [
        bill_row(billing_month="2026-10"),
        bill_row(
            billing_month="2024-01",
            receivable_amount="300.00",
            initial_paid_amount="50.00",
            initial_received_on=date(2024, 1, 15),
            initial_receipt_reason="历史累计已缴",
        ),
        bill_row(billing_month="2024-02", receivable_amount="200.00", initial_paid_amount="200.00"),
        bill_row(billing_month="2024-03", receivable_amount="0.00"),
    ]
    batch_id = bill_imports.upload(rows, extension)
    preview = bill_imports.get(batch_id)
    assert preview["status"] == "preview_ready", preview
    assert preview["statistics"]["preview"]["create_rows"] == 4
    assert preview["statistics"]["preview"]["error_rows"] == 0
    assert bill_imports.counts() == dict(bills=0, entries=0, operations=0, audits=0)
    assert summary(preview) == {
        "receivable_cents": ("60000", "60000"),
        "initial_paid_cents": ("25000", "25000"),
        "outstanding_cents": ("35000", "35000"),
    }
    projected = bill_imports.get(batch_id, "/rows")["items"]
    assert len(projected) == 4
    assert projected[1]["business_values"] == {
        "matched_house_label": "first-community／01栋／001",
        "billing_month": "2024-01",
        "receivable_cents": 30000,
        "initial_paid_cents": 5000,
        "outstanding_cents": 25000,
    }
    for row in projected:
        assert "_prepared" not in row["normalized_values"]
        assert "house_id" not in row["business_values"]
    result = bill_imports.execute(batch_id)
    assert result["status"] == "completed", result
    assert result["statistics"]["execution"]["created_rows"] == 4
    assert bill_imports.counts() == dict(bills=4, entries=2, operations=4, audits=4)
    with workspace.platform.factory() as db:
        bills = list(db.scalars(select(Bill).order_by(Bill.period_start)))
        assert {item.house_id for item in bills} == {house["id"]}
        assert [(item.receivable_cents, item.settled_cents) for item in bills] == [
            (30000, 5000),
            (20000, 20000),
            (0, 0),
            (10000, 0),
        ]
        entries = list(db.scalars(select(BillSettlementEntry)))
        assert {entry.source_type for entry in entries} == {"offline"}
        assert {entry.entry_type for entry in entries} == {"receipt"}
        assert {entry.received_on for entry in entries} == {date(2024, 1, 15), None}
        operations = list(db.scalars(select(BillOperation)))
        assert all(
            op.actor_id == workspace.account_id
            and op.actor_type == "admin"
            and op.action == "create"
            and op.result["bill"]["id"] == op.bill_id
            for op in operations
        )
        assert all(
            op.status == "succeeded" and op.target_type == "bill"
            for op in db.scalars(select(ImportOperation))
        )
        audits = list(
            db.scalars(select(AdminAuditLog).where(AdminAuditLog.action == "property.bill.create"))
        )
        assert {audit.target_id for audit in audits} == {item.id for item in bills}
        assert all(
            audit.scope == "property_admin"
            and audit.property_company_id == workspace.company_id
            and audit.actor_id == workspace.account_id
            for audit in audits
        )
        zero_id = next(item.id for item in bills if item.receivable_cents == 0)
    zero = workspace.client.get(housing_path(workspace, f"/bills/{zero_id}"))
    assert zero.status_code == 200, zero.text
    assert zero.json()["settlement_status"] == "settled"


def test_reimport_after_later_receipt_skips_original_creation_without_duplicate_payment(
    bill_imports: BillImports,
) -> None:
    workspace = bill_imports.workspace
    create_house(workspace, create_node(workspace, "01栋")["id"], "001")
    row = bill_row(initial_paid_amount="30.00")
    first_id = bill_imports.upload([row])
    assert bill_imports.execute(first_id)["status"] == "completed"
    with workspace.platform.factory() as db:
        bill = db.scalars(select(Bill)).one()
        bill_id = bill.id
    later = workspace.client.post(
        housing_path(workspace, f"/bills/{bill_id}/offline-receipts"),
        json={"expected_row_version": 1, "amount_cents": 7000},
        headers={**workspace.headers(), "Idempotency-Key": "later-receipt"},
    )
    assert later.status_code == 201, later.text
    counts = bill_imports.counts()
    second_id = bill_imports.upload([row])
    second = bill_imports.get(second_id)
    assert second["statistics"]["preview"]["skip_rows"] == 1, second
    assert set(summary(second).values()) == {("0", "0")}
    result = bill_imports.execute(second_id)
    assert result["statistics"]["execution"]["skipped_rows"] == 1, result
    assert bill_imports.counts() == counts == dict(bills=1, entries=2, operations=2, audits=1)
    with workspace.platform.factory() as db:
        persisted_bill = db.get(Bill, bill_id)
        assert persisted_bill and persisted_bill.settled_cents == 10000
        assert persisted_bill.row_version == 2
    assert bill_imports.get(first_id)["statistics"]["execution"]["created_rows"] == 1


def test_reimport_of_a_voided_successful_target_preserves_original_operation(
    bill_imports: BillImports,
) -> None:
    workspace = bill_imports.workspace
    create_house(workspace, create_node(workspace, "01栋")["id"], "001")
    first_id = bill_imports.upload([bill_row()])
    bill_imports.execute(first_id)
    with workspace.platform.factory() as db:
        operation = db.scalars(select(ImportOperation)).one()
        original_operation_id, target_id = operation.id, operation.target_id
    voided = workspace.client.post(
        housing_path(workspace, f"/bills/{target_id}/voids"),
        json={"expected_row_version": 1, "reason": "原建账作废"},
        headers={**workspace.headers(), "Idempotency-Key": "void-original"},
    )
    assert voided.status_code == 200, voided.text
    second_id = bill_imports.upload([bill_row()])
    preview = bill_imports.get(second_id)
    assert preview["statistics"]["preview"]["error_rows"] == 1, preview
    assert bill_imports.counts()["bills"] == 1
    assert "import.conflict" in {
        issue["code"] for issue in bill_imports.get(second_id, "/issues")["items"]
    }
    with workspace.platform.factory() as db:
        original = db.get(ImportOperation, original_operation_id)
        assert original and original.status == "succeeded" and original.target_id == target_id


@pytest.mark.parametrize("phase,unit", [(False, False), (True, False), (False, True), (True, True)])
def test_complete_location_matches_optional_levels_and_preserves_text_identity(
    bill_imports: BillImports, phase: bool, unit: bool
) -> None:
    workspace = bill_imports.workspace
    parent = create_node(workspace, "一期", "phase")["id"] if phase else None
    building = create_node(workspace, "01栋", parent_id=parent)
    leaf = create_node(workspace, "01单元", "unit", building["id"]) if unit else building
    house = create_house(workspace, leaf["id"], "00a", external_code="000A")
    row = bill_row(
        phase_name="一期" if phase else "",
        unit_name="01单元" if unit else "",
        room_no="00a",
        house_external_code="000A",
    )
    batch_id = bill_imports.upload([row])
    assert bill_imports.get(batch_id)["statistics"]["preview"]["create_rows"] == 1
    assert bill_imports.execute(batch_id)["status"] == "completed"
    with workspace.platform.factory() as db:
        assert db.scalars(select(Bill)).one().house_id == house["id"]


@pytest.mark.parametrize("current_code", [None, "000a"], ids=["system-empty", "case-mismatch"])
def test_auxiliary_house_code_never_replaces_complete_location(
    bill_imports: BillImports, current_code: str | None
) -> None:
    workspace = bill_imports.workspace
    node = create_node(workspace, "01栋")
    create_house(workspace, node["id"], "001", external_code=current_code)
    create_house(workspace, node["id"], "002", external_code="000A")
    batch_id = bill_imports.upload([bill_row(house_external_code="000A")])
    preview = bill_imports.get(batch_id)
    assert preview["statistics"]["preview"]["error_rows"] == 1, preview
    assert {issue["code"] for issue in bill_imports.get(batch_id, "/issues")["items"]} == {
        "import.house_external_code_mismatch"
    }
    assert bill_imports.counts()["bills"] == 0


@pytest.mark.parametrize("omitted", ["phase_name", "unit_name"])
def test_an_omitted_existing_location_level_is_not_a_descendant_wildcard(
    bill_imports: BillImports, omitted: str
) -> None:
    workspace = bill_imports.workspace
    phase = create_node(workspace, "一期", "phase")
    building = create_node(workspace, "01栋", parent_id=phase["id"])
    unit = create_node(workspace, "01单元", "unit", building["id"])
    create_house(workspace, unit["id"], "001")
    row = bill_row(phase_name="一期", unit_name="01单元")
    row[omitted] = ""
    batch_id = bill_imports.upload([row])
    preview = bill_imports.get(batch_id)
    assert preview["statistics"]["preview"]["error_rows"] == 1, preview
    assert {issue["code"] for issue in bill_imports.get(batch_id, "/issues")["items"]} == {
        "import.house_location_invalid"
    }
    assert bill_imports.counts()["bills"] == 0


@pytest.mark.parametrize(
    "changes",
    [
        {"initial_paid_amount": ""},
        {"initial_paid_amount": "100.01"},
        {"receivable_amount": "-1"},
        {"receivable_amount": "0.001"},
        {"initial_paid_amount": "10.00", "initial_received_on": "2099-01-01"},
    ],
    ids=["missing-paid", "overpaid", "negative-receivable", "excess-precision", "future-receipt"],
)
def test_invalid_financial_input_is_not_silently_defaulted_or_rounded(
    bill_imports: BillImports, changes: dict[str, Any]
) -> None:
    workspace = bill_imports.workspace
    create_house(workspace, create_node(workspace, "01栋")["id"], "001")
    batch_id = bill_imports.upload([bill_row(**changes)])
    preview = bill_imports.get(batch_id)
    assert preview["status"] == "preview_ready", preview
    assert preview["statistics"]["preview"]["error_rows"] == 1
    assert preview["statistics"]["preview"]["create_rows"] == 0
    assert set(summary(preview).values()) == {("0", "0")}
    assert bill_imports.get(batch_id, "/issues")["items"]
    assert bill_imports.counts() == dict(bills=0, entries=0, operations=0, audits=0)


@pytest.mark.parametrize(
    "invalid_fields",
    [
        {"receivable_amount": "bad"},
        {"manual_amount_reason": ""},
        {"initial_paid_amount": ""},
        {"house_external_code": "wrong-code"},
    ],
    ids=["bad-amount", "missing-reason", "missing-paid", "auxiliary-code-mismatch"],
)
def test_invalid_duplicate_still_rejects_both_house_month_rows(
    bill_imports: BillImports, invalid_fields: dict[str, Any]
) -> None:
    workspace = bill_imports.workspace
    create_house(workspace, create_node(workspace, "01栋")["id"], "001")
    batch_id = bill_imports.upload([bill_row(), bill_row(**invalid_fields)])
    preview = bill_imports.get(batch_id)
    assert preview["status"] == "preview_ready", preview
    assert preview["statistics"]["preview"]["error_rows"] == 2
    assert preview["statistics"]["preview"]["create_rows"] == 0
    rows = bill_imports.get(batch_id, "/rows")["items"]
    assert [row["precheck_status"] for row in rows] == ["error", "error"]
    duplicate_issues = [
        issue
        for issue in bill_imports.get(batch_id, "/issues")["items"]
        if issue["code"] == "import.duplicate_in_file"
    ]
    assert {issue["row_no"] for issue in duplicate_issues} == {2, 3}
    assert set(summary(preview).values()) == {("0", "0")}
    rejected = workspace.client.post(
        f"{PREFIX}/import-batches/{batch_id}/confirm",
        json={
            "preview_version": preview["preview"]["version"],
            "preview_fingerprint": preview["preview"]["fingerprint"],
            "apply_policy": "valid_rows_only",
            "include_warning_rows": False,
        },
        headers={**workspace.headers(), "Idempotency-Key": uuid4().hex},
    )
    assert rejected.status_code == 409, rejected.text
    assert rejected.json()["code"] == "import.no_executable_rows"
    drain_worker(workspace.platform.factory, bill_imports.worker)
    assert bill_imports.counts() == dict(bills=0, entries=0, operations=0, audits=0)


def import_permissions() -> set[str]:
    return {
        f"property.import.{action}"
        for action in (
            "read",
            "create",
            "upload",
            "precheck",
            "execute",
            "retry",
            "recover",
            "cancel",
        )
    } | {"property.bill.create", "property.bill.read", "property.bill_receipt.create"}


def test_positive_paid_on_an_invalid_row_blocks_entire_batch_without_receipt_permission(
    bill_imports: BillImports,
) -> None:
    workspace = bill_imports.workspace
    create_house(workspace, create_node(workspace, "01栋")["id"], "001")
    set_permissions(workspace, import_permissions() - {"property.bill_receipt.create"})
    batch_id = bill_imports.upload(
        [bill_row(), bill_row(billing_month="bad", initial_paid_amount="10.00")]
    )
    batch = bill_imports.get(batch_id)
    assert batch["status"] == "blocked" and batch["last_error_code"] == "auth.forbidden", batch
    for policy in ("all_rows", "valid_rows_only"):
        denied = workspace.client.post(
            f"{PREFIX}/import-batches/{batch_id}/confirm",
            json={
                "preview_version": 1,
                "preview_fingerprint": "a" * 64,
                "apply_policy": policy,
                "include_warning_rows": False,
            },
            headers={**workspace.headers(), "Idempotency-Key": uuid4().hex},
        )
        assert denied.status_code == 403, denied.text
    assert bill_imports.counts() == dict(bills=0, entries=0, operations=0, audits=0)


def test_revoking_receipt_permission_after_confirmation_stops_execution(
    bill_imports: BillImports,
) -> None:
    workspace = bill_imports.workspace
    create_house(workspace, create_node(workspace, "01栋")["id"], "001")
    batch_id = bill_imports.upload([bill_row(initial_paid_amount="10.00")])
    bill_imports.confirm(batch_id)
    set_permissions(workspace, import_permissions() - {"property.bill_receipt.create"})
    drain_worker(workspace.platform.factory, bill_imports.worker)
    result = bill_imports.get(batch_id)
    assert result["status"] == "blocked" and result["last_error_code"] == "auth.forbidden", result
    assert bill_imports.counts() == dict(bills=0, entries=0, operations=0, audits=0)


def test_prepared_house_is_not_rebound_when_another_house_takes_its_old_room(
    bill_imports: BillImports,
) -> None:
    workspace = bill_imports.workspace
    node = create_node(workspace, "01栋")
    original = create_house(workspace, node["id"], "001")
    batch_id = bill_imports.upload([bill_row()])
    bill_imports.confirm(batch_id)
    renamed = workspace.client.patch(
        housing_path(workspace, f"/houses/{original['id']}"),
        json={"room_no": "002"},
        headers=workspace.headers(),
    )
    assert renamed.status_code == 200, renamed.text
    replacement = create_house(workspace, node["id"], "001")
    assert replacement["id"] != original["id"]
    drain_worker(workspace.platform.factory, bill_imports.worker)
    result = bill_imports.get(batch_id)
    assert result["statistics"]["execution"]["failed_rows"] == 1, result
    assert "import.house_location_changed" in {
        issue["code"] for issue in bill_imports.get(batch_id, "/issues")["items"]
    }
    assert bill_imports.counts()["bills"] == 0


@pytest.mark.parametrize(
    "same_content", [True, False], ids=["same-creation-skips", "different-conflicts"]
)
def test_manual_creation_committed_after_preview_is_checked_before_import_write(
    bill_imports: BillImports, same_content: bool
) -> None:
    workspace = bill_imports.workspace
    house = create_house(workspace, create_node(workspace, "01栋")["id"], "001")
    batch_id = bill_imports.upload([bill_row()])
    bill_imports.confirm(batch_id)
    manual = create_manual(bill_imports, house["id"], amount=10000 if same_content else 9000)
    drain_worker(workspace.platform.factory, bill_imports.worker)
    result = bill_imports.get(batch_id)
    execution = result["statistics"]["execution"]
    assert (execution["skipped_rows"], execution["failed_rows"]) == (
        (1, 0) if same_content else (0, 1)
    ), result
    assert bill_imports.counts() == dict(bills=1, entries=0, operations=1, audits=1)
    with workspace.platform.factory() as db:
        assert db.scalars(select(Bill)).one().id == manual["bill"]["id"]


def test_skip_plan_cannot_create_when_its_target_is_voided_after_final_revalidation(
    bill_imports: BillImports, monkeypatch: MonkeyPatch
) -> None:
    workspace = bill_imports.workspace
    house = create_house(workspace, create_node(workspace, "01栋")["id"], "001")
    manual = create_manual(bill_imports, house["id"])
    original_id = manual["bill"]["id"]
    batch_id = bill_imports.upload([bill_row()])
    preview = bill_imports.get(batch_id)
    assert preview["statistics"]["preview"]["skip_rows"] == 1, preview
    bill_imports.confirm(batch_id)
    voided_between_check_and_write = False

    def void_target_before_shared_creation(db: Session, **kwargs: Any) -> BillCreationResult:
        nonlocal voided_between_check_and_write
        response = workspace.client.post(
            housing_path(workspace, f"/bills/{original_id}/voids"),
            json={"expected_row_version": 1, "reason": "预览目标在执行复核后作废"},
            headers={**workspace.headers(), "Idempotency-Key": "void-between-check-and-write"},
        )
        assert response.status_code == 200, response.text
        voided_between_check_and_write = True
        return create_bill(db, **kwargs)

    monkeypatch.setattr(bill_adapter, "create_bill", void_target_before_shared_creation)
    drain_worker(workspace.platform.factory, bill_imports.worker)
    result = bill_imports.get(batch_id)
    assert voided_between_check_and_write
    assert result["statistics"]["execution"]["created_rows"] == 0, result
    assert result["statistics"]["execution"]["failed_rows"] == 1, result
    assert bill_imports.counts() == dict(bills=1, entries=0, operations=2, audits=1)
    with workspace.platform.factory() as db:
        original = db.scalars(select(Bill)).one()
        assert original.id == original_id and original.lifecycle_status == "voided"
    assert "import.conflict" in {
        issue["code"] for issue in bill_imports.get(batch_id, "/issues")["items"]
    }


@pytest.mark.parametrize("target_state", ["available", "voided", "relabeled"])
def test_uncertain_skip_recovers_only_the_fixed_original_creation_without_new_writes(
    bill_imports: BillImports, monkeypatch: MonkeyPatch, target_state: str
) -> None:
    workspace = bill_imports.workspace
    house = create_house(workspace, create_node(workspace, "01栋")["id"], "001")
    manual = create_manual(bill_imports, house["id"])
    original_id = manual["bill"]["id"]
    batch_id = bill_imports.upload([bill_row()])
    assert bill_imports.get(batch_id)["statistics"]["preview"]["skip_rows"] == 1
    bill_imports.confirm(batch_id)
    execute = bill_adapter.BillImportAdapter.execute
    lost_skip_result = False

    def lose_the_skip_result(
        self: bill_adapter.BillImportAdapter, plan: ImportPlan, context: ImportContext, db: Session
    ) -> Mapping[str, Any]:
        nonlocal lost_skip_result
        result = execute(self, plan, context, db)
        assert result == {"status": "skipped", "target_type": "bill", "target_id": original_id}
        lost_skip_result = True
        raise ImportOutcomeUnknown

    with monkeypatch.context() as patch:
        patch.setattr(bill_adapter.BillImportAdapter, "execute", lose_the_skip_result)
        drain_worker(workspace.platform.factory, bill_imports.worker)
    blocked = bill_imports.get(batch_id)
    assert lost_skip_result and blocked["status"] == "blocked", blocked
    assert blocked["statistics"]["execution"]["uncertain_rows"] == 1
    with workspace.platform.factory() as db:
        operation = db.scalars(select(ImportOperation)).one()
        original_key = operation.operation_key
        assert operation.status == "uncertain"
        assert (
            db.scalar(
                select(BillOperation).where(
                    BillOperation.idempotency_key == "import_" + original_key
                )
            )
            is None
        )
        prepared = db.scalars(select(ImportRow)).one().normalized_values
        assert prepared and prepared["_prepared"]["target_id"] == original_id

    if target_state == "voided":
        changed = workspace.client.post(
            housing_path(workspace, f"/bills/{original_id}/voids"),
            json={"expected_row_version": 1, "reason": "恢复前原目标已作废"},
            headers={**workspace.headers(), "Idempotency-Key": "void-before-recover"},
        )
        assert changed.status_code == 200, changed.text
    elif target_state == "relabeled":
        changed = workspace.client.patch(
            housing_path(workspace, f"/houses/{house['id']}"),
            json={"room_no": "002"},
            headers=workspace.headers(),
        )
        assert changed.status_code == 200, changed.text
    before_recovery = bill_imports.counts()
    recovery = workspace.client.post(
        f"{PREFIX}/import-batches/{batch_id}/recover",
        json={"reason": "按原目标核实已存在账单"},
        headers={**workspace.headers(), "Idempotency-Key": "recover-uncertain-skip"},
    )
    assert recovery.status_code == 202, recovery.text
    drain_worker(workspace.platform.factory, bill_imports.worker)
    result = bill_imports.get(batch_id)
    if target_state == "available":
        assert result["status"] == "completed", result
        assert result["statistics"]["execution"]["skipped_rows"] == 1
        assert result["statistics"]["execution"]["uncertain_rows"] == 0
    else:
        assert (
            result["status"] == "blocked" and result["last_error_code"] == "import.result_uncertain"
        ), result
        assert result["statistics"]["execution"]["uncertain_rows"] == 1
        assert result["statistics"]["execution"]["skipped_rows"] == 0
    assert result["statistics"]["execution"]["created_rows"] == 0
    assert bill_imports.counts() == before_recovery
    with workspace.platform.factory() as db:
        final = db.scalars(select(ImportOperation)).one()
        assert final.operation_key == original_key
        assert final.status == ("skipped" if target_state == "available" else "uncertain")
        if target_state == "available":
            assert final.target_id == original_id
        assert (
            db.scalar(
                select(BillOperation).where(
                    BillOperation.idempotency_key == "import_" + original_key
                )
            )
            is None
        )


def test_audit_insert_failure_rolls_back_the_whole_bill_and_preserves_other_rows(
    bill_imports: BillImports,
) -> None:
    workspace = bill_imports.workspace
    create_house(workspace, create_node(workspace, "01栋")["id"], "001")
    batch_id = bill_imports.upload(
        [
            bill_row(initial_paid_amount="10.00"),
            bill_row(billing_month="2024-02", initial_paid_amount="20.00"),
        ]
    )
    bill_imports.confirm(batch_id)
    rejected = False

    def reject_one_bill_audit(
        mapper: Mapper[AdminAuditLog], connection: Connection, record: AdminAuditLog
    ) -> None:
        nonlocal rejected
        if record.action == "property.bill.create" and not rejected:
            rejected = True
            raise ImportExecutionFailure("import.execution_failed")

    event.listen(AdminAuditLog, "before_insert", reject_one_bill_audit)
    try:
        drain_worker(workspace.platform.factory, bill_imports.worker)
    finally:
        event.remove(AdminAuditLog, "before_insert", reject_one_bill_audit)
    result = bill_imports.get(batch_id)
    assert rejected
    assert result["status"] == "partial_failed", result
    assert result["statistics"]["execution"]["created_rows"] == 1
    assert result["statistics"]["execution"]["failed_rows"] == 1
    assert bill_imports.counts() == dict(bills=1, entries=1, operations=1, audits=1)
    with workspace.platform.factory() as db:
        bill = db.scalars(select(Bill)).one()
        assert bill.period_start == date(2024, 2, 1) and bill.settled_cents == 2000
        assert sorted(db.scalars(select(ImportOperation.status))) == ["failed", "succeeded"]
        assert sorted(db.scalars(select(ImportRow.execution_status))) == ["created", "failed"]
