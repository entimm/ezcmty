"""Planner acceptance at 8,000 batches, 50,000 staged rows and 8,000 stage tasks."""

import json
from collections.abc import Callable, Iterator
from datetime import timedelta
from typing import Any

from sqlalchemy import event, insert, text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session
from sqlalchemy.sql import Executable, Select
from tests.support.imports.data import NOW, ImportSetup

from backend_app.core.identifiers import new_id
from backend_app.models.imports import ImportBatch, ImportRow, ImportTask
from backend_app.models.property import PropertyCompany
from backend_app.repositories.imports import queries
from backend_app.repositories.imports.tasks import claim_tasks

COMPANY_COUNT = 20
BATCH_COUNT = 8_000
ROW_BATCH_COUNT = 50
ROWS_PER_BATCH = 1_000
ROW_COUNT = ROW_BATCH_COUNT * ROWS_PER_BATCH
CHUNK_SIZE = 500


def _populate(db: Session, setup: ImportSetup) -> list[str]:
    company_ids = [setup.company_id, *(new_id() for _ in range(COMPANY_COUNT - 1))]
    db.execute(
        insert(PropertyCompany),
        [
            {"id": company_id, "code": f"PLAN_{number:02}", "name": "Query plan company"}
            for number, company_id in enumerate(company_ids[1:], start=1)
        ],
    )
    batch_ids = [new_id() for _ in range(BATCH_COUNT)]
    for start in range(0, BATCH_COUNT, CHUNK_SIZE):
        db.execute(
            insert(ImportBatch),
            [
                {
                    "id": batch_ids[number],
                    "property_company_id": company_ids[number % COMPANY_COUNT],
                    "scope_type": "company",
                    "scope_snapshot": {"property_company_id": company_ids[number % COMPANY_COUNT]},
                    "template_key": "query_plan_records",
                    "template_version_no": 1,
                    "template_config_hash": "a" * 64,
                    "created_by_scope": "platform_admin",
                    "created_by_id": setup.actor_id,
                    "request_id": "query-plans",
                    "total_rows": ROWS_PER_BATCH if number < ROW_BATCH_COUNT else 0,
                    "created_at": NOW + timedelta(minutes=number),
                    "updated_at": NOW + timedelta(minutes=number),
                    "retention_until": NOW + timedelta(minutes=number, days=30),
                }
                for number in range(start, min(start + CHUNK_SIZE, BATCH_COUNT))
            ],
        )
    for start in range(0, ROW_COUNT, CHUNK_SIZE):
        db.execute(
            insert(ImportRow),
            [
                {
                    "id": new_id(),
                    "batch_id": batch_ids[number // ROWS_PER_BATCH],
                    "source_row_no": number % ROWS_PER_BATCH + 2,
                    "raw_values": {"code": f"record-{number}", "name": "Representative record"},
                    "created_at": NOW,
                    "updated_at": NOW,
                }
                for number in range(start, min(start + CHUNK_SIZE, ROW_COUNT))
            ],
        )
    for start in range(0, BATCH_COUNT, CHUNK_SIZE):
        values: list[dict[str, Any]] = []
        for number in range(start, min(start + CHUNK_SIZE, BATCH_COUNT)):
            status = "ready" if number < 80 else "running" if number < 100 else "completed"
            values.append(
                {
                    "id": new_id(),
                    "batch_id": batch_ids[number],
                    "phase": "precheck",
                    "status": status,
                    "next_run_at": NOW - timedelta(minutes=1)
                    if number < 60
                    else NOW + timedelta(days=1),
                    "lease_expires_at": NOW + timedelta(seconds=-5 if number < 90 else 30)
                    if status == "running"
                    else None,
                    "completed_at": NOW if status == "completed" else None,
                    "checkpoint": {
                        "schema_version": 1,
                        "target_preview_version": 1,
                        "next_row_no": 2,
                    },
                    "created_at": NOW,
                    "updated_at": NOW,
                }
            )
        db.execute(insert(ImportTask), values)
    db.commit()
    return batch_ids


def _plan_nodes(plan: dict[str, Any]) -> Iterator[dict[str, Any]]:
    yield plan
    for child in plan.get("Plans", []):
        yield from _plan_nodes(child)


def _explain(db: Session, statement: Select[Any]) -> dict[str, Any]:
    compiled = statement.compile(
        dialect=db.get_bind().dialect, compile_kwargs={"literal_binds": True}
    )
    result = db.scalar(text("EXPLAIN (FORMAT JSON) " + str(compiled)))
    assert isinstance(result, list) and len(result) == 1
    return result[0]["Plan"]  # type: ignore[no-any-return]


def test_import_queries_use_indexes_at_representative_scale(
    import_setup: ImportSetup, record_property: Callable[[str, object], None]
) -> None:
    """Explain actual repository statements with normal planner settings, after ANALYZE."""
    with import_setup.factory() as db:
        batch_ids = _populate(db, import_setup)
        db.execute(text("ANALYZE import_batches, import_rows, import_tasks"))
        db.commit()
        assert db.scalar(text("SHOW enable_seqscan")) == "on"
        captured: list[Select[Any]] = []

        def capture(
            connection: Connection,
            statement: Executable,
            multiparams: Any,
            params: Any,
            execution_options: Any,
        ) -> None:
            if isinstance(statement, Select):
                captured.append(statement)

        connection = db.connection()
        event.listen(connection, "before_execute", capture)
        try:
            queries.batches(
                db, "platform_admin", import_setup.company_id, {"page": 2, "page_size": 20}
            )
            history = captured[-1]
            batch = db.get(ImportBatch, batch_ids[0])
            assert batch is not None
            queries.rows(db, batch, {"page": 2, "page_size": 20})
            rows = captured[-1]
            captured.clear()
            assert claim_tasks(db, now=NOW)
            scheduling = captured[0]
        finally:
            event.remove(connection, "before_execute", capture)
        # Claim facts belong to this test only; EXPLAIN reads the original queue distribution.
        db.rollback()
        plans = {
            "company_history_page": _explain(db, history),
            "batch_row_page": _explain(db, rows),
            "ready_and_expired_task_schedule": _explain(db, scheduling),
        }
        indexes = {
            label: {node["Index Name"] for node in _plan_nodes(plan) if "Index Name" in node}
            for label, plan in plans.items()
        }
        assert "ix_import_batch_company_time" in indexes["company_history_page"], plans[
            "company_history_page"
        ]
        assert indexes["batch_row_page"] & {
            "uq_import_row_number",
            "ix_import_row_validation",
            "ix_import_row_execution",
        }, plans["batch_row_page"]
        assert "ix_import_task_ready" in indexes["ready_and_expired_task_schedule"], plans[
            "ready_and_expired_task_schedule"
        ]
        assert "ix_import_task_running" in indexes["ready_and_expired_task_schedule"], plans[
            "ready_and_expired_task_schedule"
        ]
        record_property(
            "representative_scale",
            json.dumps(
                {
                    "companies": COMPANY_COUNT,
                    "batches": BATCH_COUNT,
                    "rows": ROW_COUNT,
                    "tasks": BATCH_COUNT,
                    "ready_tasks": 80,
                    "running_tasks": 20,
                }
            ),
        )
        record_property(
            "selected_indexes",
            json.dumps({label: sorted(names) for label, names in indexes.items()}, sort_keys=True),
        )
