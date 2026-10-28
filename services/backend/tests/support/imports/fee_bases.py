"""Shared real-API setup for fee-basis import acceptance tests."""

import csv
from dataclasses import dataclass
from io import BytesIO, StringIO
from typing import Any
from uuid import uuid4

from openpyxl import Workbook
from sqlalchemy import func, select

from backend_app.core.config import get_settings
from backend_app.domain.imports.registry import ImportDefinition
from backend_app.import_definitions.catalog import get_import_registry
from backend_app.models.billing import FeeBasisVersion
from backend_app.services.worker.imports.pipeline import ImportWorkerService
from tests.support.housing import create_house, create_node, housing_path
from tests.support.imports.pipeline import drain_worker
from tests.support.workspace import PREFIX, WorkspaceHarness


def basis_row(**changes: Any) -> dict[str, Any]:
    return {
        "phase_name": "",
        "building_name": "01栋",
        "unit_name": "",
        "room_no": "0001",
        "house_external_code": "0001A",
        "effective_from_month": "2026-01",
        "house_usage": "住宅",
        "area_sqm": "100",
        "unit_price_amount": "2.00",
        "fixed_amount": "",
        "change_reason": "初次设置",
        **changes,
    }


@dataclass
class BasisImports:
    workspace: WorkspaceHarness
    worker: ImportWorkerService
    definition: ImportDefinition

    @classmethod
    def for_workspace(cls, workspace: WorkspaceHarness) -> BasisImports:
        return cls(
            workspace,
            ImportWorkerService(workspace.platform.factory, get_settings()),
            get_import_registry().get("property_fee_basis_versions", 1),
        )

    def house(self, room_no: str = "0001") -> dict[str, Any]:
        node = create_node(self.workspace, "01栋")
        return create_house(self.workspace, node["id"], room_no, external_code="0001A")

    def get(self, batch_id: str, suffix: str = "") -> dict[str, Any]:
        response = self.workspace.client.get(f"{PREFIX}/import-batches/{batch_id}{suffix}")
        assert response.status_code == 200, response.text
        return dict(response.json())

    def upload(self, rows: list[dict[str, Any]], extension: str = "csv") -> str:
        response = self.workspace.client.post(
            f"{PREFIX}/import-batches",
            json={
                "import_type": self.definition.key,
                "template_version_no": 1,
                "scope": {"type": "community", "id": self.workspace.community_id},
                "mode": "create",
            },
            headers={**self.workspace.headers(), "Idempotency-Key": uuid4().hex},
        )
        assert response.status_code == 201, response.text
        batch_id = str(response.json()["batch_id"])
        headers = [field.label for field in self.definition.fields]
        values = [[row.get(field.key, "") for field in self.definition.fields] for row in rows]
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
            stream_bytes = BytesIO()
            workbook.save(stream_bytes)
            workbook.close()
            content = stream_bytes.getvalue()
            media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        uploaded = self.workspace.client.post(
            f"{PREFIX}/import-batches/{batch_id}/source-file",
            files={"file": (f"bases.{extension}", content, media_type)},
            headers={**self.workspace.headers(), "Idempotency-Key": uuid4().hex},
        )
        assert uploaded.status_code == 202, uploaded.text
        self.drain()
        return batch_id

    def drain(self) -> None:
        drain_worker(self.workspace.platform.factory, self.worker)

    def confirm(self, batch_id: str, policy: str = "all_rows") -> None:
        batch = self.get(batch_id)
        assert batch["status"] == "preview_ready", batch
        response = self.workspace.client.post(
            f"{PREFIX}/import-batches/{batch_id}/confirm",
            json={
                "preview_version": batch["preview"]["version"],
                "preview_fingerprint": batch["preview"]["fingerprint"],
                "apply_policy": policy,
                "include_warning_rows": False,
            },
            headers={**self.workspace.headers(), "Idempotency-Key": uuid4().hex},
        )
        assert response.status_code == 202, response.text

    def execute(self, batch_id: str) -> dict[str, Any]:
        self.confirm(batch_id)
        self.drain()
        return self.get(batch_id)

    def manual_basis(self, house_id: str, **changes: Any) -> dict[str, Any]:
        path = housing_path(self.workspace, f"/houses/{house_id}/property-fee-basis-versions")
        versions = self.workspace.client.get(path)
        assert versions.status_code == 200, versions.text
        latest = versions.json()["items"][0]["version_no"] if versions.json()["total"] else 0
        response = self.workspace.client.post(
            path,
            json={
                "expected_latest_version_no": latest,
                "effective_from_month": "2026-01",
                "house_usage": "residential",
                "area_sqm": "100",
                "unit_price_cents": 200,
                "change_reason": "初次设置",
                **changes,
            },
            headers=self.workspace.headers(),
        )
        assert response.status_code == 201, response.text
        return dict(response.json())

    def resume(self, batch_id: str, action: str) -> dict[str, Any]:
        response = self.workspace.client.post(
            f"{PREFIX}/import-batches/{batch_id}/{action}",
            json={"selection": "retryable_only"}
            if action == "retry-failed"
            else {"reason": "核实原操作"},
            headers={**self.workspace.headers(), "Idempotency-Key": uuid4().hex},
        )
        assert response.status_code == (201 if action == "retry-failed" else 202), response.text
        return dict(response.json())

    def count(self) -> int:
        with self.workspace.platform.factory() as db:
            return int(db.scalar(select(func.count()).select_from(FeeBasisVersion)) or 0)
