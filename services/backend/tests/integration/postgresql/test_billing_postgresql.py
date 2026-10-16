from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from time import monotonic

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from tests.support.billing_services import BillingSetup
from tests.support.paths import BACKEND_ROOT

from backend_app.core.errors import AppError
from backend_app.db.base import Base
from backend_app.models.billing import Bill, BillOperation, BillSettlementEntry
from backend_app.models.housing import House
from backend_app.repositories.billing import BillingRepository
from backend_app.schemas import billing as schema
from backend_app.services.property_admin.billing import PropertyBillingService


@pytest.mark.parametrize("same_key", [True, False])
def test_concurrent_bill_creation_replays_or_conflicts(
    billing_setup: BillingSetup, same_key: bool
) -> None:
    barrier = Barrier(2)

    def create(index: int) -> str:
        barrier.wait(timeout=10)
        try:
            return billing_setup.create(key="same" if same_key else f"key-{index}").bill.id
        except AppError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(create, range(2)))
    if same_key:
        assert results[0] == results[1]
    else:
        assert results.count("billing.bill_exists") == 1
    with billing_setup.factory() as db:
        assert db.scalar(select(func.count()).select_from(Bill)) == 1
        assert db.scalar(select(func.count()).select_from(BillOperation)) == 1


@pytest.mark.parametrize("race", ["receipts", "reversals", "receipt_void"])
def test_concurrent_settlements_and_void_leave_reconciled_state(
    billing_setup: BillingSetup, race: str
) -> None:
    s = billing_setup
    created = s.create(paid=3000 if race == "reversals" else 0)
    barrier = Barrier(2)

    def change(index: int) -> str:
        with s.factory() as db:
            service = PropertyBillingService(db)
            barrier.wait(timeout=10)
            try:
                if race == "reversals":
                    result = service.write(
                        s.housing.context,
                        s.housing.community_id,
                        "reverse_receipt",
                        schema.BillReasonAction(expected_row_version=1, reason="误录"),
                        f"race-{index}",
                        "request",
                        bill_id=created.bill.id,
                        entry_id=created.settlement_entries[0].id,
                    )
                elif race == "receipt_void" and index == 1:
                    result = service.write(
                        s.housing.context,
                        s.housing.community_id,
                        "void",
                        schema.BillReasonAction(expected_row_version=1, reason="错误账单"),
                        "race-void",
                        "request",
                        bill_id=created.bill.id,
                    )
                else:
                    result = service.write(
                        s.housing.context,
                        s.housing.community_id,
                        "receipt",
                        schema.ReceiptCreate(expected_row_version=1, amount_cents=7000),
                        f"race-{index}",
                        "request",
                        bill_id=created.bill.id,
                    )
                return result.operation.action
            except AppError as exc:
                return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(change, range(2)))
    assert sum(not value.startswith("billing.") for value in results) == 1
    with s.factory() as db:
        bill = db.get(Bill, created.bill.id)
        assert bill and bill.row_version == 2
        assert bill.settled_cents == db.scalar(
            select(func.coalesce(func.sum(BillSettlementEntry.amount_cents), 0)).where(
                BillSettlementEntry.bill_id == bill.id
            )
        )
        assert 0 <= bill.settled_cents <= bill.receivable_cents
        if bill.lifecycle_status == "voided":
            assert bill.settled_cents == 0


@pytest.mark.parametrize("resource", ["basis", "operation", "entry", "bill_facts", "bill_totals"])
def test_database_rejects_history_edits_and_unreconciled_totals(
    billing_setup: BillingSetup, resource: str
) -> None:
    s = billing_setup
    created = s.create(paid=3000)
    with s.factory() as db:
        basis = PropertyBillingService(db).create_basis(
            s.housing.context,
            s.housing.community_id,
            s.house_id,
            schema.FeeBasisCreate(
                expected_latest_version_no=0,
                effective_from_month="2026-01",
                house_usage="residential",
                fixed_amount_cents=0,
                change_reason="初始",
            ),
            "basis",
        )
        sql, params = {
            "basis": (
                "UPDATE property_fee_basis_versions SET change_reason='changed' WHERE id=:id",
                {"id": basis.id},
            ),
            "operation": ("DELETE FROM bill_operations WHERE id=:id", {"id": created.operation.id}),
            "entry": (
                "UPDATE bill_settlement_entries SET amount_cents=100 WHERE id=:id",
                {"id": created.settlement_entries[0].id},
            ),
            "bill_facts": (
                "UPDATE bills SET receivable_cents=20000, row_version=row_version+1 WHERE id=:id",
                {"id": created.bill.id},
            ),
            "bill_totals": (
                "UPDATE bills SET settled_cents=0, row_version=row_version+1 WHERE id=:id",
                {"id": created.bill.id},
            ),
        }[resource]
        with pytest.raises(IntegrityError):
            db.execute(text(sql), params)
            db.commit()
        db.rollback()
        persisted = db.get(Bill, created.bill.id)
        assert persisted and persisted.settled_cents == 3000


def test_migration_matches_metadata(billing_setup: BillingSetup) -> None:
    with billing_setup.factory() as db, db.connection() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        assert compare_metadata(context, Base.metadata) == []


def test_billing_downgrade_refuses_populated_history(billing_setup: BillingSetup) -> None:
    created = billing_setup.create(paid=3000)
    with pytest.raises(RuntimeError, match="billing data exists"):
        command.downgrade(Config(str(BACKEND_ROOT / "alembic.ini")), "20261015_property_housing")
    with billing_setup.factory() as db:
        bill = db.get(Bill, created.bill.id)
        assert bill and bill.settled_cents == 3000
        assert db.get(BillOperation, created.operation.id) is not None
        assert db.get(BillSettlementEntry, created.settlement_entries[0].id) is not None
        assert db.scalar(text("SELECT version_num FROM alembic_version")) == "20261017_house_claims"


def test_independent_bills_share_parent_locks_without_serializing(
    billing_setup: BillingSetup, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = billing_setup
    first = s.create()
    second = s.create(month="2026-02", key="second")
    held = Event()
    release = Event()
    original = BillingRepository.bill

    def lock(
        repo: BillingRepository, community_id: str, bill_id: str, *, lock: bool = False
    ) -> Bill | None:
        bill = original(repo, community_id, bill_id, lock=lock)
        if lock and bill_id == first.bill.id:
            held.set()
            assert release.wait(10)
        return bill

    monkeypatch.setattr(BillingRepository, "bill", lock)

    def receipt(bill_id: str) -> schema.BillWriteResult:
        with s.factory() as db:
            return PropertyBillingService(db).write(
                s.housing.context,
                s.housing.community_id,
                "receipt",
                schema.ReceiptCreate(expected_row_version=1, amount_cents=1),
                bill_id,
                "request",
                bill_id=bill_id,
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        one = pool.submit(receipt, first.bill.id)
        try:
            assert held.wait(10)
            # Same company, actor, community, ancestors and house; only the bill differs.
            two = pool.submit(receipt, second.bill.id)
            assert two.result(timeout=5).bill.settled_cents == 1
        finally:
            release.set()
        assert one.result(timeout=10).bill.settled_cents == 1


def test_writer_rechecks_house_disabled_while_waiting(billing_setup: BillingSetup) -> None:
    s = billing_setup
    with s.factory() as blocker, ThreadPoolExecutor(max_workers=1) as pool:
        house = blocker.scalar(
            select(House).where(House.id == s.house_id).with_for_update(of=House)
        )
        assert house
        house.enabled = False
        pid = blocker.scalar(text("SELECT pg_backend_pid()"))
        future = pool.submit(s.create)
        with s.factory() as observer:
            deadline = monotonic() + 5
            while not observer.scalar(
                text(
                    "SELECT EXISTS (SELECT 1 FROM pg_stat_activity "
                    "WHERE :pid = ANY(pg_blocking_pids(pid)))"
                ),
                {"pid": pid},
            ):
                assert monotonic() < deadline, "Bill creation never waited for the house lock"
        blocker.commit()
        with pytest.raises(AppError) as caught:
            future.result(timeout=10)
        assert caught.value.code == "property.housing_disabled"


def test_basis_revision_and_creation_coordinate_on_house(billing_setup: BillingSetup) -> None:
    s = billing_setup
    with s.factory() as db:
        first = PropertyBillingService(db).create_basis(
            s.housing.context,
            s.housing.community_id,
            s.house_id,
            schema.FeeBasisCreate(
                expected_latest_version_no=0,
                effective_from_month="2026-01",
                house_usage="residential",
                fixed_amount_cents=10000,
                change_reason="初始",
            ),
            "first",
        )
    barrier = Barrier(2)

    def create() -> str:
        with s.factory() as db:
            barrier.wait(timeout=10)
            try:
                result = PropertyBillingService(db).write(
                    s.housing.context,
                    s.housing.community_id,
                    "create",
                    schema.BillCreate(
                        house_id=s.house_id,
                        billing_month="2026-01",
                        amount_source="basis",
                        basis_version_id=first.id,
                        expected_calculation_rule_version=1,
                        expected_receivable_cents=10000,
                    ),
                    "create",
                    "request",
                )
                assert (
                    result.bill.basis_version_id == first.id
                    and result.bill.receivable_cents == 10000
                )
                return "created"
            except AppError as exc:
                return exc.code

    def revise() -> None:
        with s.factory() as db:
            barrier.wait(timeout=10)
            PropertyBillingService(db).create_basis(
                s.housing.context,
                s.housing.community_id,
                s.house_id,
                schema.FeeBasisCreate(
                    expected_latest_version_no=1,
                    effective_from_month="2026-01",
                    house_usage="residential",
                    fixed_amount_cents=20000,
                    change_reason="纠错",
                ),
                "revised",
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        one, two = pool.submit(create), pool.submit(revise)
        assert one.result(timeout=10) in {"created", "billing.basis_changed"}
        two.result(timeout=10)
    with s.factory() as db:
        preview = PropertyBillingService(db).calculate(
            s.housing.context,
            s.housing.community_id,
            s.house_id,
            schema.FeeCalculationRequest(billing_month="2026-01"),
        )
        assert preview.basis and preview.basis.version_no == 2 and preview.receivable_cents == 20000
