from concurrent.futures import ThreadPoolExecutor
from threading import Event
from time import monotonic

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, sessionmaker
from tests.support.housing_services import provision_housing

from backend_app.core.admin_sessions import AdminSessionStore
from backend_app.domain.imports.types import ImportContext, ImportScope
from backend_app.models.admin import AdminAuditLog
from backend_app.models.housing import HouseOwner
from backend_app.models.property import PropertyCompany
from backend_app.schemas.housing import HouseCreate, HouseOwnerCreate, HouseOwnerUpdate
from backend_app.services.property_admin.housing import PropertyHousingService
from backend_app.services.worker.imports.adapters.house_owners import HouseOwnerImportAdapter


@pytest.mark.parametrize("reuse_entry", ["successful_result", "unknown_skip"])
def test_owner_result_reuse_protects_the_record_until_caller_commit(
    real_admin: tuple[sessionmaker[Session], AdminSessionStore], reuse_entry: str
) -> None:
    factory, store = real_admin
    setup = provision_housing(factory, store)
    with factory() as db:
        house = PropertyHousingService(db).create_house(
            setup.context,
            setup.community_id,
            HouseCreate(
                space_node_id=setup.node_id,
                room_no="0001",
                owners=[HouseOwnerCreate(name="张甲", phone="13800000000")],
            ),
            "house",
        )
        house_id = house.id
        owner_id = db.scalar(select(HouseOwner.id).where(HouseOwner.house_id == house_id))
        assert owner_id is not None
    adapter = HouseOwnerImportAdapter()
    context = ImportContext(
        "property_admin",
        setup.context.account_id,
        ImportScope(setup.company_id, "community", setup.community_id),
        "owner-reuse",
        frozenset(setup.context.permissions),
        phase="apply" if reuse_entry == "successful_result" else None,
    )
    with factory() as db:
        preparation = adapter.prepare(
            {"building_name": "楼栋", "room_no": "0001", "name": "张甲", "phone": "13800000000"},
            context,
            db,
        )
        prepared = preparation.prepared
        assert prepared is not None and not preparation.problems
        assert prepared["action"] == "skip" and prepared["target_id"] == owner_id
    started = Event()
    completed = Event()
    editor_pids: list[int] = []

    def edit() -> str:
        with factory() as db:
            editor_pid = db.scalar(text("SELECT pg_backend_pid()"))
            assert isinstance(editor_pid, int)
            editor_pids.append(editor_pid)
            started.set()
            result = PropertyHousingService(db).update_owner(
                setup.context,
                setup.community_id,
                house_id,
                owner_id,
                HouseOwnerUpdate(name="张乙"),
                "owner-edit",
            )
            completed.set()
            return result.name

    # Close the reuse transaction before joining the thread, including on assertion failure.
    with ThreadPoolExecutor(max_workers=1) as pool, factory() as reuse:
        if reuse_entry == "successful_result":
            assert not adapter.revalidate(
                prepared,
                context,
                reuse,
                target={"target_type": "house_owner", "target_id": owner_id},
            )
        else:
            assert adapter.resolve_operation("original-operation", prepared, context, reuse) == {
                "status": "skipped",
                "target_type": "house_owner",
                "target_id": owner_id,
            }
        protector_pid = reuse.scalar(text("SELECT pg_backend_pid()"))
        pending = pool.submit(edit)
        assert started.wait(10)
        with factory() as observer:
            deadline = monotonic() + 5
            while not observer.scalar(
                text("SELECT :protector_pid = ANY(pg_blocking_pids(:editor_pid))"),
                {"protector_pid": protector_pid, "editor_pid": editor_pids[0]},
            ):
                assert monotonic() < deadline, (
                    "Manual editing never waited for the reuse transaction"
                )
                assert not completed.is_set(), "Manual editing committed before result reuse"
        assert not pending.done() and not completed.is_set()
        reuse.commit()
        assert pending.result(timeout=10) == "张乙"
        assert completed.is_set()
    with factory() as db:
        assert db.scalar(select(HouseOwner.name).where(HouseOwner.id == owner_id)) == "张乙"
        assert (
            db.scalar(
                select(func.count())
                .select_from(AdminAuditLog)
                .where(AdminAuditLog.action == "property.house_owner.create")
            )
            == 1
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(AdminAuditLog)
                .where(AdminAuditLog.request_id == "owner-reuse")
            )
            == 0
        )


def test_precheck_target_revalidation_does_not_hold_a_company_lock(
    real_admin: tuple[sessionmaker[Session], AdminSessionStore],
) -> None:
    factory, store = real_admin
    setup = provision_housing(factory, store)
    with factory() as db:
        PropertyHousingService(db).create_house(
            setup.context,
            setup.community_id,
            HouseCreate(
                space_node_id=setup.node_id,
                room_no="0001",
                owners=[HouseOwnerCreate(name="张甲", phone="13800000000")],
            ),
            "house",
        )
    adapter = HouseOwnerImportAdapter()
    context = ImportContext(
        "property_admin",
        setup.context.account_id,
        ImportScope(setup.company_id, "community", setup.community_id),
        "owner-precheck",
        frozenset(setup.context.permissions),
        phase="precheck",
    )
    with factory() as precheck, factory() as writer:
        preparation = adapter.prepare(
            {"building_name": "楼栋", "room_no": "0001", "name": "张甲", "phone": "13800000000"},
            context,
            precheck,
        )
        prepared = preparation.prepared
        assert prepared is not None and not preparation.problems
        assert not adapter.revalidate(
            prepared,
            context,
            precheck,
            target={"target_type": "house_owner", "target_id": prepared["target_id"]},
        )
        assert precheck.in_transaction()
        # A second connection must acquire this row while the precheck remains open.
        company = writer.scalar(
            select(PropertyCompany)
            .where(PropertyCompany.id == setup.company_id)
            .with_for_update(nowait=True)
        )
        assert company is not None
