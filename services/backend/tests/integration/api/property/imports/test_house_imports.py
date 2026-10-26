import csv
from collections.abc import Mapping
from dataclasses import dataclass
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
from backend_app.models.housing import House, HouseOwner, SpaceNode
from backend_app.models.imports import ImportOperation, ImportRow
from backend_app.services.worker.imports.adapters.houses import HouseImportAdapter
from backend_app.services.worker.imports.pipeline import ImportWorkerService


@dataclass
class HouseImports:
    workspace: WorkspaceHarness
    worker: ImportWorkerService
    definition: ImportDefinition

    def get(self, batch_id: str, suffix: str = "") -> dict[str, Any]:
        response = self.workspace.client.get(f"{PREFIX}/import-batches/{batch_id}{suffix}")
        assert response.status_code == 200, response.text
        return dict(response.json())

    def upload(
        self, rows: list[dict[str, Any]], extension: str = "csv", *, extra_column: str | None = None
    ) -> str:
        created = self.workspace.client.post(
            f"{PREFIX}/import-batches",
            json={
                "import_type": "houses",
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
            writer.writerow(
                [field.label for field in fields] + ([extra_column] if extra_column else [])
            )
            writer.writerows(
                [
                    [row.get(field.key, "") for field in fields]
                    + (["test"] if extra_column else [])
                    for row in rows
                ]
            )
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
            files={"file": (f"houses.{extension}", content, media_type)},
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

    def counts(self) -> tuple[int, int, int]:
        with self.workspace.platform.factory() as db:
            counts = [
                int(db.scalar(select(func.count()).select_from(model)) or 0)
                for model in (House, HouseOwner, SpaceNode)
            ]
            return counts[0], counts[1], counts[2]

    def resume(self, batch_id: str, action: str) -> dict[str, Any]:
        response = self.workspace.client.post(
            f"{PREFIX}/import-batches/{batch_id}/{action}",
            json={"selection": "retryable_only"}
            if action == "retry-failed"
            else {"reason": "按原操作核实或重试"},
            headers={**self.workspace.headers(), "Idempotency-Key": uuid4().hex},
        )
        assert response.status_code == (201 if action == "retry-failed" else 202), response.text
        return dict(response.json())


@pytest.fixture
def house_imports(
    workspace: WorkspaceHarness, monkeypatch: MonkeyPatch, tmp_path: Path
) -> HouseImports:
    monkeypatch.setenv("APP_IMPORT_STORAGE_ROOT", str(tmp_path / "private-imports"))
    get_settings.cache_clear()
    return HouseImports(
        workspace,
        ImportWorkerService(workspace.platform.factory, get_settings()),
        get_import_registry().get("houses", 1),
    )


def house_row(**changes: Any) -> dict[str, Any]:
    return {
        "phase_name": "",
        "building_name": "01栋",
        "unit_name": "",
        "room_no": "0001",
        "floor_no": "-1",
        "external_code": "0001A",
        **changes,
    }


@pytest.mark.parametrize("extension", ["csv", "xlsx"])
@pytest.mark.parametrize("phase,unit", [(False, False), (True, False), (False, True), (True, True)])
def test_preview_is_read_only_and_creates_only_houses(
    house_imports: HouseImports, extension: str, phase: bool, unit: bool
) -> None:
    h = house_imports
    parent = create_node(h.workspace, "一期", "phase") if phase else None
    building = create_node(h.workspace, "01栋", parent_id=parent["id"] if parent else None)
    if unit:
        create_node(h.workspace, "01单元", "unit", parent_id=building["id"])
    before = h.counts()
    batch_id = h.upload(
        [house_row(phase_name="一期" if phase else "", unit_name="01单元" if unit else "")],
        extension,
    )
    preview = h.get(batch_id)
    assert preview["status"] == "preview_ready", preview
    assert preview["statistics"]["preview"]["create_rows"] == 1
    assert preview["business_preview"]["summary"] == []
    assert h.counts() == before
    row = h.get(batch_id, "/rows")["items"][0]
    assert row["business_values"]["room_no"] == "0001"
    assert "_prepared" not in str(row)
    result = h.execute(batch_id)
    assert result["status"] == "completed", result
    assert h.counts() == (1, 0, before[2])
    with h.workspace.platform.factory() as db:
        house = db.scalars(select(House)).one()
        assert (house.room_no, house.floor_no, house.external_code) == ("0001", -1, "0001A")
        audit = db.scalars(
            select(AdminAuditLog).where(AdminAuditLog.action == "property.house.create")
        ).one()
        operation = db.scalars(select(ImportOperation)).one()
        assert audit.target_id == operation.target_id == house.id
        assert operation.status == "succeeded"


@pytest.mark.parametrize(
    "invalid",
    [
        {"floor_no": "1.5"},
        {"floor_no": "9" * 5000},
        {"floor_no": "32768"},
        {"external_code": "x" * 65},
    ],
)
def test_invalid_duplicate_marks_all_rows(
    house_imports: HouseImports, invalid: dict[str, Any]
) -> None:
    h = house_imports
    create_node(h.workspace, "01栋")
    batch_id = h.upload([house_row(), house_row(**invalid)])
    batch = h.get(batch_id)
    assert batch["statistics"]["preview"]["error_rows"] == 2, batch
    issues = h.get(batch_id, "/issues")["items"]
    assert {issue["row_no"] for issue in issues if issue["code"] == "import.duplicate_in_file"} == {
        2,
        3,
    }
    assert h.counts() == (0, 0, 1)


def test_current_data_controls_skip_and_conflict_without_touching_owners(
    house_imports: HouseImports,
) -> None:
    h = house_imports
    node = create_node(h.workspace, "01栋")
    house = create_house(
        h.workspace,
        node["id"],
        "0001",
        floor_no=-1,
        external_code="0001A",
        owners=[{"name": "原业主", "phone": "13800000000"}],
    )
    response = h.workspace.client.patch(
        housing_path(h.workspace, f"/houses/{house['id']}"),
        json={"enabled": False},
        headers=h.workspace.headers(),
    )
    assert response.status_code == 200
    batch_id = h.upload([house_row()])
    assert h.get(batch_id)["statistics"]["preview"]["skip_rows"] == 1
    assert h.execute(batch_id)["statistics"]["execution"]["skipped_rows"] == 1
    response = h.workspace.client.patch(
        housing_path(h.workspace, f"/houses/{house['id']}"),
        json={"external_code": "CHANGED"},
        headers=h.workspace.headers(),
    )
    assert response.status_code == 200
    changed = h.upload([house_row()])
    assert h.get(changed)["statistics"]["preview"]["error_rows"] == 1
    with h.workspace.platform.factory() as db:
        existing = db.scalars(select(House)).one()
        assert existing.external_code == "CHANGED" and not existing.enabled
        owner = db.scalars(select(HouseOwner)).one()
        assert owner.name == "原业主" and owner.phone == "13800000000"
        assert (
            db.scalar(
                select(func.count())
                .select_from(AdminAuditLog)
                .where(AdminAuditLog.action == "property.house.create")
            )
            == 1
        )


@pytest.mark.parametrize("kind", ["missing", "empty-layer", "owner-column"])
def test_missing_space_and_unexpected_owner_column_do_not_write(
    house_imports: HouseImports, kind: str
) -> None:
    h = house_imports
    if kind == "empty-layer":
        phase = create_node(h.workspace, "一期", "phase")
        create_node(h.workspace, "01栋", parent_id=phase["id"])
    before = h.counts()
    batch_id = h.upload([house_row()], extra_column="业主姓名" if kind == "owner-column" else None)
    result = h.get(batch_id)
    assert result["status"] in {"preview_ready", "blocked", "failed"}, result
    assert result["statistics"]["preview"]["create_rows"] == 0
    assert h.counts() == before


@pytest.mark.parametrize("same", [True, False])
def test_manual_create_after_preview_is_skipped_or_conflicts(
    house_imports: HouseImports, same: bool
) -> None:
    h = house_imports
    node = create_node(h.workspace, "01栋")
    batch_id = h.upload([house_row()])
    h.confirm(batch_id)
    create_house(
        h.workspace, node["id"], "0001", floor_no=-1, external_code="0001A" if same else "OTHER"
    )
    drain_worker(h.workspace.platform.factory, h.worker)
    result = h.get(batch_id)["statistics"]["execution"]
    assert (result["skipped_rows"], result["failed_rows"]) == ((1, 0) if same else (0, 1))
    assert h.counts() == (1, 0, 1)


@pytest.mark.parametrize("change", ["rename", "disable", "target-room", "target-floor"])
def test_confirmed_plan_rechecks_fixed_path_and_target(
    house_imports: HouseImports, change: str
) -> None:
    h = house_imports
    node = create_node(h.workspace, "01栋")
    house = (
        create_house(h.workspace, node["id"], "0001", floor_no=-1, external_code="0001A")
        if change.startswith("target")
        else None
    )
    batch_id = h.upload([house_row()])
    h.confirm(batch_id)
    data: dict[str, Any]
    if house:
        suffix = f"/houses/{house['id']}"
        data = {"room_no": "0002"} if change == "target-room" else {"floor_no": 2}
    else:
        suffix = f"/space-nodes/{node['id']}"
        data = {"name": "新楼栋"} if change == "rename" else {"enabled": False}
    changed = h.workspace.client.patch(
        housing_path(h.workspace, suffix), json=data, headers=h.workspace.headers()
    )
    assert changed.status_code == 200, changed.text
    if change == "target-room":
        create_house(h.workspace, node["id"], "0001", floor_no=-1, external_code="0001A")
    if change == "rename":
        create_node(h.workspace, "01栋")
    before = h.counts()
    drain_worker(h.workspace.platform.factory, h.worker)
    assert h.get(batch_id)["statistics"]["execution"]["failed_rows"] == 1
    assert h.counts() == before


def test_revoked_create_permission_blocks_execution(house_imports: HouseImports) -> None:
    h = house_imports
    create_node(h.workspace, "01栋")
    batch_id = h.upload([house_row()])
    h.confirm(batch_id)
    set_permissions(
        h.workspace,
        {"property.housing.read"},
    )
    drain_worker(h.workspace.platform.factory, h.worker)
    result = h.get(batch_id)
    assert result["status"] == "blocked" and result["last_error_code"] == "auth.forbidden", result
    assert h.counts() == (0, 0, 1)


def test_audit_failure_rolls_back_house_and_import_result(house_imports: HouseImports) -> None:
    h = house_imports
    create_node(h.workspace, "01栋")
    batch_id = h.upload([house_row(), house_row(room_no="0002")])
    h.confirm(batch_id)
    rejected = False

    def reject(mapper: Mapper[AdminAuditLog], connection: Connection, audit: AdminAuditLog) -> None:
        nonlocal rejected
        if audit.action == "property.house.create" and not rejected:
            rejected = True
            raise ImportExecutionFailure("import.execution_failed")

    event.listen(AdminAuditLog, "before_insert", reject)
    try:
        drain_worker(h.workspace.platform.factory, h.worker)
    finally:
        event.remove(AdminAuditLog, "before_insert", reject)
    result = h.get(batch_id)
    assert rejected and result["status"] == "partial_failed", result
    assert h.counts() == (1, 0, 1)
    with h.workspace.platform.factory() as db:
        assert db.scalars(select(House.room_no)).one() == "0002"
        assert sorted(db.scalars(select(ImportOperation.status))) == ["failed", "succeeded"]
        assert sorted(db.scalars(select(ImportRow.execution_status))) == ["created", "failed"]
        assert (
            db.scalar(
                select(func.count())
                .select_from(AdminAuditLog)
                .where(AdminAuditLog.action == "property.house.create")
            )
            == 1
        )


@pytest.mark.parametrize("skip,changed", [(True, False), (True, True), (False, False)])
def test_unknown_result_keeps_original_operation_and_never_recreates(
    house_imports: HouseImports, monkeypatch: MonkeyPatch, skip: bool, changed: bool
) -> None:
    h = house_imports
    node = create_node(h.workspace, "01栋")
    if skip:
        create_house(h.workspace, node["id"], "0001", floor_no=-1, external_code="0001A")
    batch_id = h.upload([house_row()])
    h.confirm(batch_id)
    original = HouseImportAdapter.execute

    def unknown(
        self: HouseImportAdapter, plan: ImportPlan, context: ImportContext, db: Session
    ) -> Mapping[str, Any]:
        original(self, plan, context, db)
        raise ImportOutcomeUnknown

    with monkeypatch.context() as patch:
        patch.setattr(HouseImportAdapter, "execute", unknown)
        drain_worker(h.workspace.platform.factory, h.worker)
    assert h.get(batch_id)["statistics"]["execution"]["uncertain_rows"] == 1
    with h.workspace.platform.factory() as db:
        key = db.scalars(select(ImportOperation.operation_key)).one()
        if changed:
            db.scalars(select(House)).one().floor_no = 2
            db.commit()
    before = h.counts()
    h.resume(batch_id, "recover")
    drain_worker(h.workspace.platform.factory, h.worker)
    result = h.get(batch_id)
    assert result["status"] == ("completed" if skip and not changed else "blocked"), result
    assert h.counts() == before
    with h.workspace.platform.factory() as db:
        assert db.scalars(select(ImportOperation.operation_key)).one() == key


@pytest.mark.parametrize("rename", [True, False])
def test_retry_uses_original_prepared_path_and_preserves_history(
    house_imports: HouseImports, monkeypatch: MonkeyPatch, rename: bool
) -> None:
    h = house_imports
    node = create_node(h.workspace, "01栋")
    batch_id = h.upload([house_row()])
    h.confirm(batch_id)

    def fail(*args: Any, **kwargs: Any) -> Mapping[str, Any]:
        raise ImportExecutionFailure("import.system_error", retryable=True)

    with monkeypatch.context() as patch:
        patch.setattr(HouseImportAdapter, "execute", fail)
        drain_worker(h.workspace.platform.factory, h.worker)
    original = h.get(batch_id)
    assert original["statistics"]["execution"]["retryable_failed_rows"] == 1
    with h.workspace.platform.factory() as db:
        key = db.scalars(select(ImportOperation.operation_key)).one()
    if rename:
        changed = h.workspace.client.patch(
            housing_path(h.workspace, f"/space-nodes/{node['id']}"),
            json={"name": "更名"},
            headers=h.workspace.headers(),
        )
        assert changed.status_code == 200
        create_node(h.workspace, "01栋")
    retry = h.resume(batch_id, "retry-failed")
    drain_worker(h.workspace.platform.factory, h.worker)
    retried = h.get(retry["batch"]["batch_id"])
    assert retried["statistics"]["preview"]["error_rows"] == (1 if rename else 0), retried
    if not rename:
        assert h.execute(retry["batch"]["batch_id"])["statistics"]["execution"]["created_rows"] == 1
    after = h.get(batch_id)["statistics"]
    assert after["total_rows"] == original["statistics"]["total_rows"]
    assert after["preview"] == original["statistics"]["preview"]
    for field, value in original["statistics"]["execution"].items():
        if field != "retryable_failed_rows":
            assert after["execution"][field] == value
    assert after["execution"]["retryable_failed_rows"] == (1 if rename else 0)
    with h.workspace.platform.factory() as db:
        assert db.scalars(select(ImportOperation.operation_key)).one() == key
    assert h.counts() == ((0, 0, 2) if rename else (1, 0, 1))


def test_reimport_reuses_success_without_duplicate_audit_and_compares_current_data(
    house_imports: HouseImports,
) -> None:
    h = house_imports
    create_node(h.workspace, "01栋")
    first = h.upload([house_row()])
    completed = h.execute(first)
    second = h.upload([house_row()])
    assert h.execute(second)["statistics"]["execution"]["skipped_rows"] == 1
    with h.workspace.platform.factory() as db:
        assert db.scalar(select(func.count()).select_from(ImportOperation)) == 1
        house = db.scalars(select(House)).one()
        house.floor_no = 3
        db.commit()
    conflict = h.upload([house_row()])
    assert h.get(conflict)["statistics"]["preview"]["error_rows"] == 1
    assert h.get(first)["statistics"] == completed["statistics"]
    with h.workspace.platform.factory() as db:
        assert db.scalars(select(ImportOperation.status)).one() == "succeeded"
        assert (
            db.scalar(
                select(func.count())
                .select_from(AdminAuditLog)
                .where(AdminAuditLog.action == "property.house.create")
            )
            == 1
        )
    assert h.counts() == (1, 0, 1)


def test_grouped_housing_maintenance_runs_house_only_import_without_creating_owners(
    house_imports: HouseImports,
) -> None:
    h = house_imports
    create_node(h.workspace, "01栋")
    permissions = {"property.housing.manage"}
    set_permissions(h.workspace, permissions)
    batch_id = h.upload([house_row(floor_no="", external_code=" ")])
    assert h.execute(batch_id)["statistics"]["execution"]["created_rows"] == 1
    with h.workspace.platform.factory() as db:
        house = db.scalars(select(House)).one()
        assert house.floor_no is None and house.external_code is None
    assert h.counts() == (1, 0, 1)


@pytest.mark.parametrize("same", [True, False])
def test_overlapping_batches_share_business_identity_and_commit_once(
    house_imports: HouseImports, same: bool
) -> None:
    h = house_imports
    create_node(h.workspace, "01栋")
    first = h.upload([house_row()])
    second = h.upload([house_row(external_code="0001A" if same else "DIFFERENT")])
    h.confirm(first)
    h.confirm(second)
    drain_worker(h.workspace.platform.factory, h.worker)
    assert h.get(first)["statistics"]["execution"]["created_rows"] == 1
    other = h.get(second)["statistics"]["execution"]
    assert (other["skipped_rows"], other["failed_rows"]) == ((1, 0) if same else (0, 1))
    assert h.counts() == (1, 0, 1)
    with h.workspace.platform.factory() as db:
        assert db.scalar(select(func.count()).select_from(ImportOperation)) == (1 if same else 2)
        assert (
            db.scalar(
                select(func.count())
                .select_from(AdminAuditLog)
                .where(AdminAuditLog.action == "property.house.create")
            )
            == 1
        )


def test_grouped_housing_maintenance_preserves_owner_aggregate_validation(
    house_imports: HouseImports,
) -> None:
    h = house_imports
    node = create_node(h.workspace, "01栋")
    set_permissions(h.workspace, {"property.housing.manage"})
    response = h.workspace.client.post(
        housing_path(h.workspace, "/houses"),
        json={
            "space_node_id": node["id"],
            "room_no": "0001",
            "owners": [
                {"name": "业主", "phone": "13800000000"},
                {"name": "业主", "phone": "+8613800000000"},
            ],
        },
        headers=h.workspace.headers(),
    )
    assert (
        response.status_code == 409 and response.json()["code"] == "property.duplicate_house_owner"
    )
    assert h.counts() == (0, 0, 1)
