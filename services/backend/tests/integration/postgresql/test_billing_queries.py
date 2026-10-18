import json
from datetime import date
from typing import Any

from sqlalchemy import event, insert, text
from tests.support.billing_services import BillingSetup

from backend_app.core.identifiers import new_id
from backend_app.domain.billing import next_month
from backend_app.models.admin import utc_now
from backend_app.models.billing import Bill, BillOperation, BillSettlementEntry
from backend_app.models.housing import House
from backend_app.repositories.billing import BillingRepository
from backend_app.services.property_admin.billing import PropertyBillingService


def test_representative_bills_use_pending_index_and_batch_related_reads(
    billing_setup: BillingSetup,
) -> None:
    s = billing_setup
    now = utc_now()
    with s.factory() as db:
        houses = [
            {
                "id": new_id(),
                "community_id": s.housing.community_id,
                "space_node_id": s.housing.node_id,
                "room_no": f"S{index:03}",
                "created_at": now,
                "updated_at": now,
            }
            for index in range(200)
        ]
        db.execute(insert(House), houses)
        bills: list[dict[str, Any]] = []
        operations: list[dict[str, Any]] = []
        entries: list[dict[str, Any]] = []
        # Five years, 200 houses, 90% paid; all inserts use the real consistency triggers.
        for house in houses:
            for month in range(60):
                start = date(2020 + month // 12, month % 12 + 1, 1)
                bill_id, operation_id = new_id(), new_id()
                paid = 10000 if month % 10 else 0
                bills.append(
                    {
                        "id": bill_id,
                        "property_company_id": s.housing.company_id,
                        "community_id": s.housing.community_id,
                        "house_id": house["id"],
                        "bill_type": "property_fee",
                        "period_granularity": "month",
                        "period_start": start,
                        "period_end": next_month(start),
                        "amount_source": "manual",
                        "receivable_cents": 10000,
                        "settled_cents": paid,
                        "lifecycle_status": "active",
                        "house_label_snapshot": f"小区／楼栋／{house['room_no']}",
                        "manual_amount_reason": "历史",
                        "row_version": 1,
                        "created_by": s.housing.context.account_id,
                        "created_at": now,
                        "updated_at": now,
                    }
                )
                operations.append(
                    {
                        "id": operation_id,
                        "property_company_id": s.housing.company_id,
                        "bill_id": bill_id,
                        "bill_version": 1,
                        "action": "create",
                        "idempotency_key": bill_id,
                        "request_fingerprint": "a" * 64,
                        "result": {},
                        "response_status": 201,
                        "actor_id": s.housing.context.account_id,
                        "request_id": "scale",
                        "created_at": now,
                    }
                )
                if paid:
                    entries.append(
                        {
                            "id": new_id(),
                            "bill_id": bill_id,
                            "operation_id": operation_id,
                            "entry_type": "receipt",
                            "source_type": "offline",
                            "amount_cents": paid,
                            "created_at": now,
                        }
                    )
        db.execute(insert(Bill), bills)
        db.execute(insert(BillOperation), operations)
        db.execute(insert(BillSettlementEntry), entries)
        db.commit()
        db.execute(text("ANALYZE bills"))
        captured: list[tuple[str, Any]] = []

        def record(
            conn: Any, cursor: Any, statement: str, parameters: Any, context: Any, executemany: bool
        ) -> None:
            captured.append((statement, parameters))

        connection = db.connection()
        event.listen(connection, "before_cursor_execute", record)
        filters: dict[str, Any] = {
            "page": 1,
            "page_size": 20,
            "sort": "-period_start",
            "lifecycle_status": "active",
            "outstanding_only": True,
        }
        try:
            page, total = BillingRepository(db, s.housing.company_id).bill_list(
                s.housing.community_id, today=date(2026, 1, 1), **filters
            )
        finally:
            event.remove(connection, "before_cursor_execute", record)
        assert len(captured) == 1 and len(page) == 20 and total == 1200
        statement, parameters = captured[0]
        plan: dict[str, Any] = connection.exec_driver_sql(
            f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {statement}", parameters
        ).scalar_one()[0]
        assert "ix_bill_pending" in json.dumps(plan)
        captured.clear()
        event.listen(connection, "before_cursor_execute", record)
        try:
            view = PropertyBillingService(db).list_bills(
                s.housing.context, s.housing.community_id, **filters
            )
        finally:
            event.remove(connection, "before_cursor_execute", record)
        assert view.total == 1200 and len(view.items) == 20
        # Community, paged bills/count, houses, ancestor paths and one batched reservation read.
        assert len(captured) == 5
        filters["page_size"] = 100
        captured.clear()
        event.listen(connection, "before_cursor_execute", record)
        try:
            view = PropertyBillingService(db).list_bills(
                s.housing.context, s.housing.community_id, **filters
            )
        finally:
            event.remove(connection, "before_cursor_execute", record)
        assert len(view.items) == 100 and len(captured) == 5
        filters["page"] = 999
        empty, total = BillingRepository(db, s.housing.company_id).bill_list(
            s.housing.community_id, today=date(2026, 1, 1), **filters
        )
        assert not empty and total == 1200
        print(
            f"Billing plan: 12000 bills / 10800 receipts; pending={plan['Execution Time']}ms; "
            "5 reads for 20 or 100 rows"
        )
