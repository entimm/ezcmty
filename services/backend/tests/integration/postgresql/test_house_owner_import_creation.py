from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker
from tests.support.housing_services import provision_housing

from backend_app.core.admin_sessions import AdminSessionStore
from backend_app.core.errors import AppError
from backend_app.domain.imports.types import ImportContext, ImportScope
from backend_app.models.admin import AdminAuditLog
from backend_app.models.housing import HouseOwner
from backend_app.schemas.housing import HouseCreate, HouseOwnerCreate
from backend_app.services.property_admin.housing import PropertyHousingService
from backend_app.services.worker.imports.adapters.house_owners import HouseOwnerImportAdapter


@pytest.mark.parametrize("other_entry", ["manual", "import"])
def test_entries_concurrently_register_one_owner_with_one_audit(
    real_admin: tuple[sessionmaker[Session], AdminSessionStore], other_entry: str
) -> None:
    factory, store = real_admin
    setup = provision_housing(factory, store)
    with factory() as db:
        house = PropertyHousingService(db).create_house(
            setup.context,
            setup.community_id,
            HouseCreate(space_node_id=setup.node_id, room_no="0001"),
            "house",
        )
        house_id = house.id
    adapter = HouseOwnerImportAdapter()
    context = ImportContext(
        "property_admin",
        setup.context.account_id,
        ImportScope(setup.company_id, "community", setup.community_id),
        "race",
        frozenset(setup.context.permissions),
    )
    with factory() as db:
        preparation = adapter.prepare(
            {"building_name": "楼栋", "room_no": "0001", "name": "业主", "phone": "13800000000"},
            context,
            db,
        )
        assert preparation.prepared is not None and not preparation.problems
        plan = adapter.plan(preparation.prepared)
    barrier = Barrier(2)

    def create(entry: str) -> str:
        with factory() as db:
            barrier.wait(timeout=10)
            try:
                if entry == "manual":
                    PropertyHousingService(db).create_owner(
                        setup.context,
                        setup.community_id,
                        house_id,
                        HouseOwnerCreate(name="业主", phone="+8613800000000"),
                        "manual-race",
                    )
                    return "created"
                result = adapter.execute(plan, context, db)
                db.commit()
                return str(result["status"])
            except AppError as error:
                return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(create, ["import", other_entry]))
    assert results.count("created") == 1, results
    assert all(
        result in {"created", "skipped", "property.duplicate_house_owner"} for result in results
    ), results
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(HouseOwner)) == 1
        assert (
            db.scalar(
                select(func.count())
                .select_from(AdminAuditLog)
                .where(AdminAuditLog.action == "property.house_owner.create")
            )
            == 1
        )
