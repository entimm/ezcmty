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
from backend_app.models.housing import House, HouseOwner
from backend_app.schemas.housing import HouseCreate
from backend_app.services.property_admin.housing import PropertyHousingService
from backend_app.services.worker.imports.adapters.houses import HouseImportAdapter


@pytest.mark.parametrize("other_entry", ["manual", "import"])
def test_entries_concurrently_create_one_house_with_one_audit(
    real_admin: tuple[sessionmaker[Session], AdminSessionStore], other_entry: str
) -> None:
    factory, store = real_admin
    setup = provision_housing(factory, store)
    adapter = HouseImportAdapter()
    context = ImportContext(
        "property_admin",
        setup.context.account_id,
        ImportScope(setup.company_id, "community", setup.community_id),
        "race",
        frozenset(setup.context.permissions),
    )
    with factory() as db:
        preparation = adapter.prepare({"building_name": "楼栋", "room_no": "0001"}, context, db)
        assert preparation.prepared is not None and not preparation.problems
        plan = adapter.plan(preparation.prepared)
    barrier = Barrier(2)

    def create(entry: str) -> str:
        with factory() as db:
            barrier.wait(timeout=10)
            try:
                if entry == "manual":
                    PropertyHousingService(db).create_house(
                        setup.context,
                        setup.community_id,
                        HouseCreate(space_node_id=setup.node_id, room_no="0001"),
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
    assert all(result in {"created", "skipped", "property.duplicate_room_no"} for result in results)
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(House)) == 1
        assert db.scalar(select(func.count()).select_from(HouseOwner)) == 0
        assert (
            db.scalar(
                select(func.count())
                .select_from(AdminAuditLog)
                .where(AdminAuditLog.action == "property.house.create")
            )
            == 1
        )
