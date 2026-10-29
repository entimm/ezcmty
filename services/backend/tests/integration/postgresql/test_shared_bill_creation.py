from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier, Event

import pytest
from sqlalchemy import func, select
from tests.support.billing_services import BillingSetup

from backend_app.core.errors import AppError
from backend_app.domain.billing.creation import BillCreationCommand, creation_fingerprint
from backend_app.domain.housing import (
    HouseLocation,
    resolve_house_location,
    revalidate_house_location,
)
from backend_app.models.admin import AdminAuditLog
from backend_app.models.billing import Bill, BillOperation, BillSettlementEntry
from backend_app.models.housing import House, SpaceNode
from backend_app.repositories.housing import HousingRepository
from backend_app.schemas import billing as schema
from backend_app.schemas import housing as housing_schema
from backend_app.services.property_account_access import property_task_context
from backend_app.services.property_admin.billing import PropertyBillingService
from backend_app.services.property_admin.housing import PropertyHousingService
from backend_app.services.property_business.bill_creation import create_bill, prepare_bill_creation


def _command(setup: BillingSetup, paid: int = 0) -> BillCreationCommand:
    return BillCreationCommand.from_input(
        {
            "house_id": setup.house_id,
            "billing_month": "2026-01",
            "amount_source": "manual",
            "receivable_cents": 10000,
            "manual_amount_reason": "历史",
            "initial_receipt": {"amount_cents": paid} if paid else None,
        }
    )


@pytest.mark.parametrize(
    ("phase", "unit"), [(False, False), (False, True), (True, False), (True, True)]
)
def test_shared_location_resolves_only_the_complete_direct_path(
    billing_setup: BillingSetup, phase: bool, unit: bool
) -> None:
    s = billing_setup
    with s.factory() as db:
        service = PropertyHousingService(db)
        parent = None
        if phase:
            parent = service.create_node(
                s.housing.context,
                s.housing.community_id,
                housing_schema.SpaceNodeCreate(node_type="phase", name="东区"),
                "phase",
            ).id
        building = service.create_node(
            s.housing.context,
            s.housing.community_id,
            housing_schema.SpaceNodeCreate(parent_id=parent, node_type="building", name="01栋"),
            "building",
        )
        parent = building.id
        if unit:
            parent = service.create_node(
                s.housing.context,
                s.housing.community_id,
                housing_schema.SpaceNodeCreate(parent_id=parent, node_type="unit", name="01单元"),
                "unit",
            ).id
        house = service.create_house(
            s.housing.context,
            s.housing.community_id,
            housing_schema.HouseCreate(space_node_id=parent, room_no="001", external_code="001a"),
            "house",
        )
        repo = HousingRepository(db, s.housing.company_id)
        location = HouseLocation(
            phase_name=" 东区 " if phase else None,
            building_name=" 01栋 ",
            unit_name="01单元" if unit else None,
            room_no="001",
            house_external_code="001a",
        )
        snapshot = resolve_house_location(repo, s.housing.community_id, location)
        assert snapshot["house_id"] == house.id
        assert snapshot["room_no"] == "001" and snapshot["house_external_code"] == "001a"
        assert snapshot["effective_enabled"]
        for wrong in [
            replace(location, room_no="1"),
            replace(location, house_external_code="001A"),
        ]:
            with pytest.raises(AppError):
                resolve_house_location(repo, s.housing.community_id, wrong)
        if phase:
            with pytest.raises(AppError) as caught:
                resolve_house_location(
                    repo, s.housing.community_id, replace(location, phase_name=None)
                )
            assert caught.value.code == "property.house_location_invalid"
        if unit:
            with pytest.raises(AppError) as caught:
                resolve_house_location(
                    repo, s.housing.community_id, replace(location, unit_name=None)
                )
            assert caught.value.code == "property.house_location_invalid"
        with pytest.raises(AppError) as caught:
            resolve_house_location(
                HousingRepository(db, "00000000-0000-7000-8000-000000000000"),
                s.housing.community_id,
                location,
            )
        assert caught.value.code == "resource.not_found"


@pytest.mark.parametrize("change", ["room", "path", "code", "floor", "disabled"])
def test_location_recheck_detects_relevant_changes_without_rebinding(
    billing_setup: BillingSetup, change: str
) -> None:
    s = billing_setup
    with s.factory() as db:
        house = db.get(House, s.house_id)
        assert house
        house.external_code = "01"
        db.commit()
        snapshot = resolve_house_location(
            HousingRepository(db, s.housing.company_id),
            s.housing.community_id,
            HouseLocation(building_name="楼栋", room_no="101", house_external_code="01"),
        )
    with s.factory() as db:
        house = db.get(House, s.house_id)
        node = db.get(SpaceNode, s.housing.node_id)
        assert house and node
        if change == "room":
            house.room_no = "102"
        elif change == "path":
            node.name = "新楼栋"
        elif change == "code":
            house.external_code = None
        elif change == "floor":
            house.floor_no = 2
        else:
            house.enabled = False
        db.commit()
        if change == "room":
            replacement = PropertyHousingService(db).create_house(
                s.housing.context,
                s.housing.community_id,
                housing_schema.HouseCreate(space_node_id=s.housing.node_id, room_no="101"),
                "replacement",
            )
            assert replacement.id != s.house_id
    with s.factory() as db:
        repo = HousingRepository(db, s.housing.company_id)
        if change in {"room", "path", "code"}:
            with pytest.raises(AppError) as caught:
                revalidate_house_location(
                    repo, s.housing.community_id, snapshot, lock=True, exclusive=True
                )
            assert caught.value.code == "property.house_location_changed"
        else:
            current = revalidate_house_location(repo, s.housing.community_id, snapshot)
            assert current["house_id"] == s.house_id
            assert current["effective_enabled"] is (change != "disabled")


def test_shared_creation_keeps_all_facts_in_the_callers_transaction(
    billing_setup: BillingSetup,
) -> None:
    s = billing_setup
    command = _command(s, paid=3000)
    with s.factory() as db:
        result = create_bill(
            db,
            company_id=s.housing.company_id,
            community_id=s.housing.community_id,
            actor_id=s.housing.context.account_id,
            command=command,
            key="batch-create",
            fingerprint=creation_fingerprint(command),
            request_id="batch",
            input_fields=frozenset(
                {
                    "house_id",
                    "billing_month",
                    "amount_source",
                    "receivable_cents",
                    "manual_amount_reason",
                    "initial_receipt",
                }
            ),
            context=property_task_context(db, s.housing.company_id, s.housing.context.account_id),
        )
        assert result.status == "created"
        assert result.result["bill"]["settled_cents"] == 3000
        db.flush()
        assert db.scalar(select(func.count()).select_from(BillOperation)) == 1
        assert db.scalar(select(func.count()).select_from(BillSettlementEntry)) == 1
        audit = db.scalar(select(AdminAuditLog).where(AdminAuditLog.target_id == result.bill_id))
        assert audit and audit.action == "property.bill.create"
        assert "due_date" not in audit.safe_metadata["changed_fields"]
        with s.factory() as observer:
            assert observer.get(Bill, result.bill_id) is None
        db.rollback()
    with s.factory() as db:
        assert db.scalar(select(func.count()).select_from(Bill)) == 0
        assert db.scalar(select(func.count()).select_from(BillOperation)) == 0
        assert db.scalar(select(func.count()).select_from(BillSettlementEntry)) == 0
        assert (
            db.scalar(
                select(func.count())
                .select_from(AdminAuditLog)
                .where(AdminAuditLog.target_type == "bill")
            )
            == 0
        )


def test_reimport_compares_original_facts_after_later_receipts_and_edits(
    billing_setup: BillingSetup,
) -> None:
    s = billing_setup
    created = s.create(paid=3000)
    command = _command(s, paid=3000)
    with s.factory() as db:
        service = PropertyBillingService(db)
        service.write(
            s.housing.context,
            s.housing.community_id,
            "receipt",
            schema.ReceiptCreate(expected_row_version=1, amount_cents=1000),
            "later-receipt",
            "later",
            bill_id=created.bill.id,
        )
        service.write(
            s.housing.context,
            s.housing.community_id,
            "update",
            schema.BillUpdate(expected_row_version=2, external_bill_no="new-external"),
            "later-edit",
            "later",
            bill_id=created.bill.id,
        )
    with s.factory() as db:
        prepared = prepare_bill_creation(
            db,
            company_id=s.housing.company_id,
            community_id=s.housing.community_id,
            command=command,
        )
        assert prepared["action"] == "skip" and prepared["target_id"] == created.bill.id
        assert prepared["initial_paid_cents"] == 3000
        result = create_bill(
            db,
            company_id=s.housing.company_id,
            community_id=s.housing.community_id,
            actor_id=s.housing.context.account_id,
            command=command,
            key="import-original",
            fingerprint=creation_fingerprint(command),
            request_id="import",
            input_fields=frozenset(),
            allow_existing=True,
            context=property_task_context(db, s.housing.company_id, s.housing.context.account_id),
        )
        assert result.status == "skipped"
        db.commit()
        assert db.scalar(select(func.count()).select_from(BillOperation)) == 3
        assert db.scalar(select(func.count()).select_from(BillSettlementEntry)) == 2
        bill = db.get(Bill, created.bill.id)
        assert bill and bill.settled_cents == 4000 and bill.external_bill_no == "new-external"
        with pytest.raises(AppError) as caught:
            prepare_bill_creation(
                db,
                company_id=s.housing.company_id,
                community_id=s.housing.community_id,
                command=_command(s, paid=4000),
            )
        assert caught.value.code == "billing.bill_exists"


def test_reusing_successful_creation_does_not_recreate_a_voided_target(
    billing_setup: BillingSetup,
) -> None:
    s = billing_setup
    command = _command(s)
    with s.factory() as db:
        created = create_bill(
            db,
            company_id=s.housing.company_id,
            community_id=s.housing.community_id,
            actor_id=s.housing.context.account_id,
            command=command,
            key="import-create",
            fingerprint=creation_fingerprint(command),
            request_id="import",
            input_fields=frozenset(),
            allow_existing=True,
            context=property_task_context(db, s.housing.company_id, s.housing.context.account_id),
        )
        db.commit()
        PropertyBillingService(db).write(
            s.housing.context,
            s.housing.community_id,
            "void",
            schema.BillReasonAction(expected_row_version=1, reason="错账"),
            "void",
            "void",
            bill_id=created.bill_id,
        )
    with s.factory() as db:
        with pytest.raises(AppError) as caught:
            create_bill(
                db,
                company_id=s.housing.company_id,
                community_id=s.housing.community_id,
                actor_id=s.housing.context.account_id,
                command=command,
                key="import-create",
                fingerprint=creation_fingerprint(command),
                request_id="retry",
                input_fields=frozenset(),
                allow_existing=True,
                context=property_task_context(
                    db, s.housing.company_id, s.housing.context.account_id
                ),
            )
        assert caught.value.code == "billing.bill_voided"
        db.rollback()
        assert db.scalar(select(func.count()).select_from(Bill)) == 1
        operation = db.scalar(select(BillOperation).where(BillOperation.id == created.operation_id))
        assert operation and operation.result["bill"]["lifecycle_status"] == "active"


def test_manual_and_shared_entry_concurrently_create_only_one_initial_receipt(
    billing_setup: BillingSetup,
) -> None:
    s = billing_setup
    barrier = Barrier(2)
    command = _command(s, paid=3000)

    def create(index: int) -> str:
        barrier.wait(timeout=10)
        if index == 0:
            try:
                return s.create(key="manual-concurrent", paid=3000).bill.id
            except AppError as error:
                assert error.code == "billing.bill_exists"
                return error.code
        with s.factory() as db:
            result = create_bill(
                db,
                company_id=s.housing.company_id,
                community_id=s.housing.community_id,
                actor_id=s.housing.context.account_id,
                command=command,
                key="shared-concurrent",
                fingerprint=creation_fingerprint(command),
                request_id="shared",
                input_fields=frozenset(),
                allow_existing=True,
                context=property_task_context(
                    db, s.housing.company_id, s.housing.context.account_id
                ),
            )
            db.commit()
            return result.bill_id

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(create, range(2)))
    assert results[0] in {results[1], "billing.bill_exists"}
    with s.factory() as db:
        assert db.scalar(select(func.count()).select_from(Bill)) == 1
        assert db.scalar(select(func.count()).select_from(BillOperation)) == 1
        assert db.scalar(select(func.count()).select_from(BillSettlementEntry)) == 1
        bill = db.get(Bill, results[1])
        assert bill and bill.settled_cents == 3000


def test_planned_skip_cannot_create_after_concurrent_target_void(
    billing_setup: BillingSetup,
) -> None:
    s = billing_setup
    original = s.create()
    command = _command(s)
    checked = Event()
    voided = Event()

    def execute_skip() -> str:
        with s.factory() as db:
            prepared = prepare_bill_creation(
                db,
                company_id=s.housing.company_id,
                community_id=s.housing.community_id,
                command=command,
            )
            assert prepared["action"] == "skip"
            checked.set()
            assert voided.wait(timeout=10)
            try:
                create_bill(
                    db,
                    company_id=s.housing.company_id,
                    community_id=s.housing.community_id,
                    actor_id=s.housing.context.account_id,
                    command=command,
                    key="planned-skip",
                    fingerprint=creation_fingerprint(command),
                    request_id="skip",
                    input_fields=frozenset(),
                    allow_existing=True,
                    expected_target_id=prepared["target_id"],
                    context=property_task_context(
                        db, s.housing.company_id, s.housing.context.account_id
                    ),
                )
            except AppError as error:
                db.rollback()
                return error.code
            raise AssertionError("A planned skip must not become a new bill")

    with ThreadPoolExecutor(max_workers=1) as pool:
        result = pool.submit(execute_skip)
        assert checked.wait(timeout=10)
        try:
            with s.factory() as db:
                PropertyBillingService(db).write(
                    s.housing.context,
                    s.housing.community_id,
                    "void",
                    schema.BillReasonAction(expected_row_version=1, reason="原单作废"),
                    "concurrent-void",
                    "void",
                    bill_id=original.bill.id,
                )
        finally:
            voided.set()
        assert result.result(timeout=10) == "billing.bill_voided"
    with s.factory() as db:
        assert db.scalar(select(func.count()).select_from(Bill)) == 1
        assert db.scalar(select(func.count()).select_from(BillOperation)) == 2
        assert db.scalar(select(func.count()).select_from(BillSettlementEntry)) == 0
        assert (
            db.scalar(
                select(func.count())
                .select_from(AdminAuditLog)
                .where(AdminAuditLog.action == "property.bill.create")
            )
            == 1
        )
