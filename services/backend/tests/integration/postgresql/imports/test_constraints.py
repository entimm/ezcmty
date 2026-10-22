from typing import Any

import pytest
from sqlalchemy.exc import IntegrityError
from tests.support.imports.data import NOW, ImportSetup, create_batch

from backend_app.models.imports import ImportArtifact, ImportBatch
from backend_app.repositories.imports.events import append_event


@pytest.mark.parametrize(
    "state",
    [
        "draft",
        "uploading",
        "prechecking",
        "preview_ready",
        "executing",
        "completed",
        "partial_failed",
        "failed",
        "blocked",
        "cancel_requested",
        "cancelled",
        "expired",
    ],
)
def test_every_documented_batch_state_is_accepted_by_native_checks(
    import_setup: ImportSetup,
    state: str,
) -> None:
    batch_id = create_batch(import_setup)
    with import_setup.factory() as db:
        batch = db.get(ImportBatch, batch_id)
        assert batch is not None
        batch.status = state
        batch.finished_at = (
            NOW
            if state in {"completed", "partial_failed", "failed", "cancelled", "expired"}
            else None
        )
        append_event(
            db,
            batch_id=batch_id,
            event_key="state",
            event_type="state_changed",
            now=NOW,
            from_status=state,
            to_status=state,
        )
        db.commit()


def test_confirmed_policy_and_error_artifact_cannot_exploit_sql_null_checks(
    import_setup: ImportSetup,
) -> None:
    batch_id = create_batch(import_setup)
    with import_setup.factory() as db:
        batch = db.get(ImportBatch, batch_id)
        assert batch is not None
        batch.confirmed_at = NOW
        batch.include_warning_rows = False
        with pytest.raises(IntegrityError):
            db.flush()
    with import_setup.factory() as db:
        db.add(
            ImportArtifact(
                batch_id=batch_id,
                artifact_kind="error_rows",
                generation=1,
                source_preview_version=None,
                storage_key="test/object.csv",
                media_type="text/csv",
                sha256="a" * 64,
                byte_size=0,
                expires_at=NOW,
            )
        )
        with pytest.raises(IntegrityError):
            db.flush()


@pytest.mark.parametrize(
    "action,success_status",
    [
        ("create", 201),
        ("retry_failed", 201),
        ("source_file", 202),
        ("precheck", 202),
        ("confirm", 202),
        ("cancel", 202),
        ("error_file", 202),
        ("recover", 202),
    ],
)
def test_request_success_status_is_bound_to_action_by_native_check(
    import_setup: ImportSetup,
    action: str,
    success_status: int,
) -> None:
    from backend_app.repositories.imports.requests import record_request

    batch_id = create_batch(import_setup)
    values: dict[str, Any] = {
        "property_company_id": import_setup.company_id,
        "actor_scope": "platform_admin",
        "actor_id": import_setup.actor_id,
        "batch_id": batch_id,
        "request_fingerprint": "a" * 64,
        "response_body": {"id": batch_id},
        "now": NOW,
        "request_scope": action if action == "create" else f"{action}:{batch_id}",
    }
    with import_setup.factory() as db:
        record_request(db, **values, idempotency_key="valid", http_status=success_status)
        db.commit()
    with import_setup.factory() as db, pytest.raises(IntegrityError) as error:
        record_request(
            db, **values, idempotency_key="wrong", http_status=202 if success_status == 201 else 201
        )
    assert (
        getattr(getattr(error.value.orig, "diag", None), "constraint_name", None)
        == "ck_import_request_response"
    )


@pytest.mark.parametrize("status", [200, 204, 299, 400])
def test_request_cannot_store_undeclared_http_success_status(
    import_setup: ImportSetup, status: int
) -> None:
    from backend_app.repositories.imports.requests import record_request

    batch_id = create_batch(import_setup)
    with import_setup.factory() as db, pytest.raises(IntegrityError) as error:
        record_request(
            db,
            property_company_id=import_setup.company_id,
            actor_scope="platform_admin",
            actor_id=import_setup.actor_id,
            batch_id=batch_id,
            request_fingerprint="a" * 64,
            response_body={"id": batch_id},
            now=NOW,
            request_scope="create",
            idempotency_key="wrong",
            http_status=status,
        )
    assert (
        getattr(getattr(error.value.orig, "diag", None), "constraint_name", None)
        == "ck_import_request_response"
    )
