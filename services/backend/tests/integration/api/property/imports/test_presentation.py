from collections.abc import Mapping, Sequence
from datetime import timedelta
from pathlib import Path
from typing import Any

from pytest import MonkeyPatch
from sqlalchemy import select
from tests.support.imports.adapter import TestRecordAdapter
from tests.support.imports.http import create_body, install_http_registry, publish_http_preview
from tests.support.workspace import PREFIX, WorkspaceHarness

from backend_app.models.imports import ImportBatch, ImportRow


class PresentationAdapter(TestRecordAdapter):
    def presentation_fields(self) -> Sequence[dict[str, str]]:
        return (
            {"key": "safe_label", "label": "业务位置", "format": "text"},
            {"key": "total", "label": "业务金额", "format": "money_cents"},
        )

    def summary_fields(self) -> Sequence[dict[str, str]]:
        return ({"key": "total", "label": "合计", "format": "money_cents"},)

    def presentation(self, prepared: Mapping[str, Any]) -> Mapping[str, Any]:
        return {
            "safe_label": prepared["code"],
            "total": 9000000000000000,
            "internal": {"command": "private"},
        }


def test_business_projection_is_whitelisted_and_summary_uses_the_complete_plan(
    workspace: WorkspaceHarness,
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    install_http_registry(monkeypatch, tmp_path, adapter=PresentationAdapter())
    created = workspace.client.post(
        f"{PREFIX}/import-batches",
        json=create_body(workspace.company_id),
        headers={**workspace.headers(), "Idempotency-Key": "business-projection"},
    )
    batch_id = created.json()["batch_id"]
    publish_http_preview(workspace.platform.factory, batch_id)
    with workspace.platform.factory() as db:
        warned = db.scalars(
            select(ImportRow).where(ImportRow.batch_id == batch_id, ImportRow.source_row_no == 3)
        ).one()
        warned.warning_count = 1
        db.commit()
    path = f"{PREFIX}/import-batches/{batch_id}"
    detail = workspace.client.get(path)
    assert detail.status_code == 200, detail.text
    summary = detail.json()["business_preview"]["summary"][0]
    assert summary["without_warning_rows"] == "9000000000000000"
    assert summary["with_warning_rows"] == "18000000000000000"
    rows = workspace.client.get(path + "/rows", params={"page_size": 1}).json()
    assert rows["total"] == 2 and len(rows["items"]) == 1
    assert rows["items"][0]["business_values"] == {"safe_label": "C2", "total": 9000000000000000}
    assert "_prepared" not in str(rows) and "internal" not in str(rows)
    with workspace.platform.factory() as db:
        row = db.scalars(
            select(ImportRow).where(ImportRow.batch_id == batch_id, ImportRow.source_row_no == 3)
        ).one()
        row.planned_action = "skip"
        batch = db.get(ImportBatch, batch_id)
        assert batch is not None
        expired = batch.retention_until + timedelta(seconds=1)
        db.commit()
    after_skip = workspace.client.get(path).json()["business_preview"]["summary"][0]
    assert (
        after_skip["without_warning_rows"] == after_skip["with_warning_rows"] == "9000000000000000"
    )
    monkeypatch.setattr("backend_app.services.imports.queries.utc_now", lambda: expired)
    assert workspace.client.get(path).json()["business_preview"] is None
