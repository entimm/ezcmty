from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from pathlib import Path
from threading import Barrier, Lock

import pytest
from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from sqlalchemy import func, select
from tests.support.imports.http import create_body, install_http_registry, publish_http_preview
from tests.support.workspace import PREFIX, WorkspaceHarness

from backend_app.models.imports import ImportBatch, ImportRequest, ImportTask
from backend_app.services.contracts.admin import AdminContext
from backend_app.services.imports.access import ImportAccess


@pytest.mark.parametrize(
    "same_key", [True, False], ids=["same-request-key", "different-request-keys"]
)
def test_simultaneous_http_confirmation_creates_one_execution_task(
    workspace: WorkspaceHarness,
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
    same_key: bool,
) -> None:
    workspace.complete_login()
    install_http_registry(monkeypatch, tmp_path)
    created = workspace.client.post(
        f"{PREFIX}/import-batches",
        json=create_body(workspace.company_id),
        headers={**workspace.headers(), "Idempotency-Key": "concurrent-confirmation-batch"},
    )
    assert created.status_code == 201, created.text
    batch_id = created.json()["batch_id"]
    publish_http_preview(workspace.platform.factory, batch_id)
    body = {
        "preview_version": 1,
        "preview_fingerprint": "b" * 64,
        "apply_policy": "all_rows",
        "include_warning_rows": False,
    }
    headers = workspace.headers()
    barrier = Barrier(2)
    session_ids: set[int] = set()
    session_lock = Lock()
    original_target = ImportAccess.target

    def simultaneous_target(
        self: ImportAccess,
        ctx: AdminContext,
        identifier: str,
        *,
        lock: bool = False,
    ) -> ImportBatch:
        if lock and identifier == batch_id:
            with session_lock:
                session_ids.add(id(self.db))
            barrier.wait(timeout=10)
        return original_target(self, ctx, identifier, lock=lock)

    monkeypatch.setattr(ImportAccess, "target", simultaneous_target)
    with ExitStack() as stack:
        clients = [
            stack.enter_context(
                TestClient(workspace.client.app, cookies=dict(workspace.client.cookies))
            )
            for _ in range(2)
        ]
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(
                    client.post,
                    f"{PREFIX}/import-batches/{batch_id}/confirm",
                    json=body,
                    headers={
                        **headers,
                        "Idempotency-Key": "same-key" if same_key else f"key-{index}",
                    },
                )
                for index, client in enumerate(clients)
            ]
            responses = [future.result(timeout=20) for future in futures]
    assert len(session_ids) == 2
    assert sorted(response.status_code for response in responses) == (
        [202, 202] if same_key else [202, 409]
    ), [response.text for response in responses]
    if same_key:
        assert responses[0].json() == responses[1].json()
    else:
        rejected = next(response for response in responses if response.status_code == 409)
        assert rejected.json()["code"] == "import.batch_state_conflict"
    with workspace.platform.factory() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(ImportTask)
                .where(ImportTask.batch_id == batch_id, ImportTask.phase == "apply")
            )
            == 1
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(ImportRequest)
                .where(
                    ImportRequest.batch_id == batch_id,
                    ImportRequest.request_scope.like("confirm:%"),
                )
            )
            == 1
        )
        batch = db.get(ImportBatch, batch_id)
        assert batch and batch.status == "executing" and batch.confirmed_at
        assert batch.apply_policy == "all_rows" and batch.include_warning_rows is False
