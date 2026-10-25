import csv
from collections.abc import Mapping
from dataclasses import dataclass
from io import BytesIO, StringIO
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
from backend_app.services.worker.imports.adapters.house_owners import HouseOwnerImportAdapter
from backend_app.services.worker.imports.pipeline import ImportWorkerService


@dataclass
class OwnerImports:
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
                "import_type": "house_owners",
                "template_version_no": 1,
                "scope": {"type": "community", "id": self.workspace.community_id},
                "mode": "create",
            },
            headers={**self.workspace.headers(), "Idempotency-Key": uuid4().hex},
        )
        assert created.status_code == 201, created.text
        batch_id = str(created.json()["batch_id"])
        fields = self.definition.fields
        headers = [field.label for field in fields] + ([extra_column] if extra_column else [])
        values = [
            [row.get(field.key, "") for field in fields] + (["test"] if extra_column else [])
            for row in rows
        ]
        if extension == "csv":
            stream = StringIO()
            writer = csv.writer(stream)
            writer.writerow(headers)
            writer.writerows(values)
            content = stream.getvalue().encode("utf-8-sig")
            media_type = "text/csv"
        else:
            workbook = Workbook()
            sheet = workbook.active
            assert sheet is not None
            sheet.title = self.definition.sheet_name
            sheet.append(headers)
            for row in values:
                sheet.append(row)
            output = BytesIO()
            workbook.save(output)
            workbook.close()
            content = output.getvalue()
            media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        uploaded = self.workspace.client.post(
            f"{PREFIX}/import-batches/{batch_id}/source-file",
            files={"file": (f"owners.{extension}", content, media_type)},
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

    def owner(self, house_id: str, **changes: Any) -> dict[str, Any]:
        response = self.workspace.client.post(
            housing_path(self.workspace, f"/houses/{house_id}/owners"),
            json={"name": "张三", "phone": "13800000000", **changes},
            headers=self.workspace.headers(),
        )
        assert response.status_code == 201, response.text
        return dict(response.json())

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
def owner_imports(workspace: WorkspaceHarness) -> OwnerImports:
    workspace.complete_login()
    return OwnerImports(
        workspace,
        ImportWorkerService(workspace.platform.factory, get_settings()),
        get_import_registry().get("house_owners", 1),
    )


def owner_row(**changes: Any) -> dict[str, Any]:
    return {
        "phase_name": "",
        "building_name": "01栋",
        "unit_name": "",
        "room_no": "0001",
        "house_external_code": "0001A",
        "name": "张三",
        "phone": "13800000000",
        **changes,
    }


def existing_house(h: OwnerImports, room_no: str = "0001") -> dict[str, Any]:
    node = create_node(h.workspace, "01栋")
    return create_house(h.workspace, node["id"], room_no, external_code="0001A")


@pytest.mark.parametrize("extension", ["csv", "xlsx"])
@pytest.mark.parametrize("phase,unit", [(False, False), (True, False), (False, True), (True, True)])
def test_preview_is_read_only_and_registration_uses_shared_normalization(
    owner_imports: OwnerImports, extension: str, phase: bool, unit: bool
) -> None:
    h = owner_imports
    parent = create_node(h.workspace, "一期", "phase") if phase else None
    building = create_node(h.workspace, "01栋", parent_id=parent["id"] if parent else None)
    node = (
        create_node(h.workspace, "01单元", "unit", parent_id=building["id"]) if unit else building
    )
    house = create_house(h.workspace, node["id"], "0001", external_code="0001A")
    before = h.counts()
    batch_id = h.upload(
        [
            owner_row(
                phase_name="一期" if phase else "",
                unit_name="01单元" if unit else "",
                name=" 张三 ",
                phone="008613800000000",
            )
        ],
        extension,
    )
    preview = h.get(batch_id)
    assert preview["status"] == "preview_ready", preview
    assert preview["statistics"]["preview"]["create_rows"] == 1
    assert h.counts() == before
    row = h.get(batch_id, "/rows")["items"][0]
    assert row["business_values"] == {
        "house_label": "／".join(
            [
                "first-community",
                *(["一期"] if phase else []),
                "01栋",
                *(["01单元"] if unit else []),
                "0001",
            ]
        ),
        "name": "张三",
        "phone": "13800000000",
        "owner_status": "新增登记",
    }
    assert "_prepared" not in str(row) and "house_snapshot" not in str(row)
    result = h.execute(batch_id)
    assert result["status"] == "completed", result
    assert h.counts() == (1, 1, before[2])
    with h.workspace.platform.factory() as db:
        owner = db.scalars(select(HouseOwner)).one()
        assert (owner.house_id, owner.name, owner.phone, owner.enabled) == (
            house["id"],
            "张三",
            "13800000000",
            True,
        )
        operation = db.scalars(select(ImportOperation)).one()
        audit = db.scalars(
            select(AdminAuditLog).where(AdminAuditLog.action == "property.house_owner.create")
        ).one()
        assert audit.target_id == operation.target_id == owner.id
        assert audit.safe_metadata == {"changed_fields": ["name", "phone"]}


@pytest.mark.parametrize("invalid_auxiliary", [False, True])
def test_normalized_duplicate_marks_every_row_even_when_auxiliary_code_is_invalid(
    owner_imports: OwnerImports, invalid_auxiliary: bool
) -> None:
    h = owner_imports
    existing_house(h)
    batch_id = h.upload(
        [
            owner_row(),
            owner_row(
                name=" 张三 ",
                phone="+8613800000000",
                house_external_code="OTHER" if invalid_auxiliary else "0001A",
            ),
        ]
    )
    result = h.get(batch_id)
    assert result["statistics"]["preview"]["error_rows"] == 2, result
    assert {
        issue["row_no"]
        for issue in h.get(batch_id, "/issues")["items"]
        if issue["code"] == "import.duplicate_in_file"
    } == {2, 3}
    assert h.counts() == (1, 0, 1)


def test_distinct_owner_combinations_and_houses_are_not_merged(owner_imports: OwnerImports) -> None:
    h = owner_imports
    house = existing_house(h)
    create_house(h.workspace, house["space_node_id"], "0002", external_code="0001A")
    batch_id = h.upload(
        [
            owner_row(),
            owner_row(name="李四"),
            owner_row(phone="13900000000"),
            owner_row(room_no="0002"),
        ]
    )
    assert h.execute(batch_id)["statistics"]["execution"]["created_rows"] == 4
    assert h.counts() == (2, 4, 1)


def test_disabled_existing_registration_is_skipped_without_enabling_or_audit(
    owner_imports: OwnerImports,
) -> None:
    h = owner_imports
    house = existing_house(h)
    owner = h.owner(house["id"])
    changed = h.workspace.client.patch(
        housing_path(h.workspace, f"/houses/{house['id']}/owners/{owner['id']}"),
        json={"enabled": False},
        headers=h.workspace.headers(),
    )
    assert changed.status_code == 200
    batch_id = h.upload([owner_row(phone="+8613800000000")])
    row = h.get(batch_id, "/rows")["items"][0]
    assert row["business_values"]["owner_status"] == "停用"
    assert h.execute(batch_id)["statistics"]["execution"]["skipped_rows"] == 1
    with h.workspace.platform.factory() as db:
        assert db.scalars(select(HouseOwner)).one().enabled is False
        assert (
            db.scalar(
                select(func.count())
                .select_from(AdminAuditLog)
                .where(AdminAuditLog.action == "property.house_owner.create")
            )
            == 1
        )


@pytest.mark.parametrize(
    "changes,extra_column",
    [
        ({"room_no": "9999"}, None),
        ({"unit_name": "不存在"}, None),
        ({"house_external_code": "OTHER"}, None),
        ({"name": ""}, None),
        ({"phone": "13800000000.0"}, None),
        ({"phone": "1.38E+10"}, None),
        ({"phone": 13800000000}, None),
        ({}, "房屋ID"),
        ({}, "启停状态"),
    ],
)
def test_invalid_input_does_not_create_business_records(
    owner_imports: OwnerImports, changes: dict[str, Any], extra_column: str | None
) -> None:
    h = owner_imports
    existing_house(h)
    batch_id = h.upload([owner_row(**changes)], "xlsx", extra_column=extra_column)
    result = h.get(batch_id)
    assert result["statistics"]["preview"]["create_rows"] == 0, result
    assert h.counts() == (1, 0, 1)


def test_manual_registration_after_confirmation_becomes_skip(owner_imports: OwnerImports) -> None:
    h = owner_imports
    house = existing_house(h)
    batch_id = h.upload([owner_row()])
    h.confirm(batch_id)
    owner = h.owner(house["id"])
    drain_worker(h.workspace.platform.factory, h.worker)
    assert h.get(batch_id)["statistics"]["execution"]["skipped_rows"] == 1
    with h.workspace.platform.factory() as db:
        assert db.scalars(select(ImportOperation.target_id)).one() == owner["id"]
    assert h.counts() == (1, 1, 1)


@pytest.mark.parametrize("change", ["node-name", "room", "owner-name", "owner-phone", "disabled"])
def test_confirmed_plan_keeps_original_house_and_owner_target(
    owner_imports: OwnerImports, change: str
) -> None:
    h = owner_imports
    house = existing_house(h)
    owner = h.owner(house["id"]) if change.startswith("owner") else None
    batch_id = h.upload([owner_row()])
    h.confirm(batch_id)
    data: dict[str, Any]
    if owner:
        suffix = f"/houses/{house['id']}/owners/{owner['id']}"
        data = {"name": "更名"} if change == "owner-name" else {"phone": "13900000000"}
    elif change == "node-name":
        suffix, data = f"/space-nodes/{house['space_node_id']}", {"name": "新楼栋"}
    else:
        suffix = f"/houses/{house['id']}"
        data = {"room_no": "0002"} if change == "room" else {"enabled": False}
    changed = h.workspace.client.patch(
        housing_path(h.workspace, suffix), json=data, headers=h.workspace.headers()
    )
    assert changed.status_code == 200, changed.text
    if change == "room":
        create_house(h.workspace, house["space_node_id"], "0001", external_code="0001A")
    elif change == "node-name":
        node = create_node(h.workspace, "01栋")
        create_house(h.workspace, node["id"], "0001", external_code="0001A")
    elif owner:
        h.owner(house["id"])
    before = h.counts()
    drain_worker(h.workspace.platform.factory, h.worker)
    assert h.get(batch_id)["statistics"]["execution"]["failed_rows"] == 1
    assert h.counts() == before


def test_successful_operation_cannot_rebind_to_replacement_registration(
    owner_imports: OwnerImports,
) -> None:
    h = owner_imports
    house = existing_house(h)
    first = h.upload([owner_row()])
    completed = h.execute(first)
    second = h.upload([owner_row(phone="008613800000000")])
    assert h.execute(second)["statistics"]["execution"]["skipped_rows"] == 1
    with h.workspace.platform.factory() as db:
        old_id = db.scalars(select(HouseOwner.id)).one()
    changed = h.workspace.client.patch(
        housing_path(h.workspace, f"/houses/{house['id']}/owners/{old_id}"),
        json={"name": "更名"},
        headers=h.workspace.headers(),
    )
    assert changed.status_code == 200
    replacement = h.owner(house["id"])
    conflict = h.upload([owner_row()])
    assert h.get(conflict)["statistics"]["preview"]["error_rows"] == 1
    assert h.get(first)["statistics"] == completed["statistics"]
    with h.workspace.platform.factory() as db:
        operation = db.scalars(select(ImportOperation)).one()
        assert (
            operation.status == "succeeded" and operation.target_id == old_id != replacement["id"]
        )


def test_grouped_housing_maintenance_completes_owner_import(
    owner_imports: OwnerImports,
) -> None:
    h = owner_imports
    existing_house(h)
    set_permissions(
        h.workspace,
        {"property.housing.manage"},
    )
    batch_id = h.upload([owner_row()])
    assert h.execute(batch_id)["statistics"]["execution"]["created_rows"] == 1


@pytest.mark.parametrize("existing", [False, True])
def test_revoked_owner_creation_permission_blocks_all_execution(
    owner_imports: OwnerImports, existing: bool
) -> None:
    h = owner_imports
    house = existing_house(h)
    if existing:
        h.owner(house["id"])
    batch_id = h.upload([owner_row()])
    h.confirm(batch_id)
    set_permissions(
        h.workspace,
        {"property.housing.read"},
    )
    drain_worker(h.workspace.platform.factory, h.worker)
    result = h.get(batch_id)
    assert result["status"] == "blocked" and result["last_error_code"] == "auth.forbidden", result
    assert h.counts() == (1, int(existing), 1)


@pytest.mark.parametrize(
    "suffix",
    ["", "/rows", "/issues", "/events", "/artifacts/error-file/download?generation=1"],
)
def test_bill_reference_permission_does_not_expose_owner_import_data(
    owner_imports: OwnerImports, suffix: str
) -> None:
    h = owner_imports
    house = existing_house(h)
    batch_id = h.upload([owner_row()])
    set_permissions(
        h.workspace,
        {"property.bill.read"},
    )
    options = h.workspace.client.get(
        housing_path(h.workspace, "/house-options"), params={"house_id": house["id"]}
    )
    assert options.status_code == 200 and options.json()["total"] == 1
    response = h.workspace.client.get(f"{PREFIX}/import-batches/{batch_id}{suffix}")
    assert response.status_code == 403, response.text
    assert "张三" not in response.text and "13800000000" not in response.text


def test_audit_failure_rolls_back_registration_and_import_result(
    owner_imports: OwnerImports,
) -> None:
    h = owner_imports
    existing_house(h)
    batch_id = h.upload([owner_row(), owner_row(name="李四")])
    h.confirm(batch_id)
    rejected = False

    def reject(mapper: Mapper[AdminAuditLog], connection: Connection, audit: AdminAuditLog) -> None:
        nonlocal rejected
        if audit.action == "property.house_owner.create" and not rejected:
            rejected = True
            raise ImportExecutionFailure("import.execution_failed")

    event.listen(AdminAuditLog, "before_insert", reject)
    try:
        drain_worker(h.workspace.platform.factory, h.worker)
    finally:
        event.remove(AdminAuditLog, "before_insert", reject)
    assert rejected and h.get(batch_id)["status"] == "partial_failed"
    with h.workspace.platform.factory() as db:
        assert db.scalars(select(HouseOwner.name)).one() == "李四"
        assert sorted(db.scalars(select(ImportOperation.status))) == ["failed", "succeeded"]
        assert sorted(db.scalars(select(ImportRow.execution_status))) == ["created", "failed"]
        assert (
            db.scalar(
                select(func.count())
                .select_from(AdminAuditLog)
                .where(AdminAuditLog.action == "property.house_owner.create")
            )
            == 1
        )


def test_error_file_excludes_sensitive_owner_values(owner_imports: OwnerImports) -> None:
    h = owner_imports
    existing_house(h)
    batch_id = h.upload([owner_row(name="隐私业主", phone="13800000000.0")])
    batch = h.get(batch_id)
    response = h.workspace.client.post(
        f"{PREFIX}/import-batches/{batch_id}/error-file",
        json={"format": "csv", "preview_version": batch["preview"]["version"]},
        headers={**h.workspace.headers(), "Idempotency-Key": uuid4().hex},
    )
    assert response.status_code == 202, response.text
    drain_worker(h.workspace.platform.factory, h.worker)
    downloaded = h.workspace.client.get(
        f"{PREFIX}/import-batches/{batch_id}/artifacts/error-file/download",
        params={"generation": response.json()["generation"]},
    )
    assert downloaded.status_code == 200, downloaded.text
    assert "隐私业主" not in downloaded.text and "13800000000" not in downloaded.text
    headers = next(csv.reader(StringIO(downloaded.content.decode("utf-8-sig"))))
    assert "name" not in headers and "phone" not in headers
    assert "room_no" in headers


def test_overlapping_batches_commit_one_registration_and_one_business_audit(
    owner_imports: OwnerImports,
) -> None:
    h = owner_imports
    existing_house(h)
    first = h.upload([owner_row()])
    second = h.upload([owner_row(phone="+8613800000000")])
    h.confirm(first)
    h.confirm(second)
    drain_worker(h.workspace.platform.factory, h.worker)
    assert h.get(first)["statistics"]["execution"]["created_rows"] == 1
    assert h.get(second)["statistics"]["execution"]["skipped_rows"] == 1
    assert h.counts() == (1, 1, 1)
    with h.workspace.platform.factory() as db:
        assert db.scalar(select(func.count()).select_from(ImportOperation)) == 1
        assert (
            db.scalar(
                select(func.count())
                .select_from(AdminAuditLog)
                .where(AdminAuditLog.action == "property.house_owner.create")
            )
            == 1
        )


@pytest.mark.parametrize("skip,changed", [(True, False), (True, True), (False, False)])
def test_unknown_result_never_creates_replacement_operation(
    owner_imports: OwnerImports, monkeypatch: MonkeyPatch, skip: bool, changed: bool
) -> None:
    h = owner_imports
    house = existing_house(h)
    if skip:
        h.owner(house["id"])
    batch_id = h.upload([owner_row()])
    h.confirm(batch_id)
    original = HouseOwnerImportAdapter.execute

    def unknown(
        self: HouseOwnerImportAdapter, plan: ImportPlan, context: ImportContext, db: Session
    ) -> Mapping[str, Any]:
        original(self, plan, context, db)
        raise ImportOutcomeUnknown

    with monkeypatch.context() as patch:
        patch.setattr(HouseOwnerImportAdapter, "execute", unknown)
        drain_worker(h.workspace.platform.factory, h.worker)
    assert h.get(batch_id)["statistics"]["execution"]["uncertain_rows"] == 1
    with h.workspace.platform.factory() as db:
        key = db.scalars(select(ImportOperation.operation_key)).one()
        if changed:
            db.scalars(select(HouseOwner)).one().name = "更名"
            db.commit()
    before = h.counts()
    h.resume(batch_id, "recover")
    drain_worker(h.workspace.platform.factory, h.worker)
    result = h.get(batch_id)
    assert result["status"] == ("completed" if skip and not changed else "blocked"), result
    assert h.counts() == before
    with h.workspace.platform.factory() as db:
        assert db.scalars(select(ImportOperation.operation_key)).one() == key


@pytest.mark.parametrize("rename", [False, True])
def test_retry_keeps_original_house_command_and_history(
    owner_imports: OwnerImports, monkeypatch: MonkeyPatch, rename: bool
) -> None:
    h = owner_imports
    house = existing_house(h)
    batch_id = h.upload([owner_row()])
    h.confirm(batch_id)

    def fail(*args: Any, **kwargs: Any) -> Mapping[str, Any]:
        raise ImportExecutionFailure("import.system_error", retryable=True)

    with monkeypatch.context() as patch:
        patch.setattr(HouseOwnerImportAdapter, "execute", fail)
        drain_worker(h.workspace.platform.factory, h.worker)
    original = h.get(batch_id)
    assert original["statistics"]["execution"]["retryable_failed_rows"] == 1
    with h.workspace.platform.factory() as db:
        key = db.scalars(select(ImportOperation.operation_key)).one()
    if rename:
        response = h.workspace.client.patch(
            housing_path(h.workspace, f"/houses/{house['id']}"),
            json={"room_no": "0002"},
            headers=h.workspace.headers(),
        )
        assert response.status_code == 200
        create_house(h.workspace, house["space_node_id"], "0001", external_code="0001A")
    retry = h.resume(batch_id, "retry-failed")
    drain_worker(h.workspace.platform.factory, h.worker)
    retry_id = retry["batch"]["batch_id"]
    retried = h.get(retry_id)
    assert retried["statistics"]["preview"]["error_rows"] == int(rename), retried
    if not rename:
        assert h.execute(retry_id)["statistics"]["execution"]["created_rows"] == 1
    after = h.get(batch_id)["statistics"]
    assert after["preview"] == original["statistics"]["preview"]
    assert after["execution"]["created_rows"] == 0
    assert after["execution"]["failed_rows"] == 1
    with h.workspace.platform.factory() as db:
        assert db.scalars(select(ImportOperation.operation_key)).one() == key
    assert h.counts() == ((2, 0, 1) if rename else (1, 1, 1))
