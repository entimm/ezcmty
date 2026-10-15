import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import event, insert, text
from sqlalchemy.orm import Session, sessionmaker

from backend_app.core.admin_sessions import AdminSessionStore
from backend_app.core.identifiers import new_id
from backend_app.models.housing import House, HouseOwner, SpaceNode
from backend_app.models.property import Community, PropertyCompany
from backend_app.repositories.housing import HousingRepository


def test_representative_housing_query_plans_and_single_statement_pagination(
    real_admin: tuple[sessionmaker[Session], AdminSessionStore],
) -> None:
    factory, _ = real_admin
    now = datetime.now(UTC)
    with factory() as db:
        company = PropertyCompany(code="SCALE", name="公司")
        db.add(company)
        db.flush()
        community = Community(
            property_company_id=company.id, code="SCALE", name="小区", address="地址"
        )
        db.add(community)
        db.flush()
        phase = SpaceNode(community_id=community.id, node_type="phase", name="东区")
        db.add(phase)
        db.flush()
        buildings = [
            {
                "id": new_id(),
                "community_id": community.id,
                "parent_id": phase.id,
                "node_type": "building",
                "name": f"{index}号楼",
                "created_at": now,
                "updated_at": now,
            }
            for index in range(50)
        ]
        db.execute(insert(SpaceNode), buildings)
        units = [
            {
                "id": new_id(),
                "community_id": community.id,
                "parent_id": building["id"],
                "node_type": "unit",
                "name": f"{index}单元",
                "created_at": now,
                "updated_at": now,
            }
            for building in buildings
            for index in range(10)
        ]
        db.execute(insert(SpaceNode), units)
        houses = [
            {
                "id": new_id(),
                "community_id": community.id,
                "space_node_id": unit["id"],
                "room_no": f"{index:03}",
                "external_code": f"X{unit_index:04}-{index:03}",
                "floor_no": index // 5,
                "created_at": now,
                "updated_at": now,
            }
            for unit_index, unit in enumerate(units)
            for index in range(50)
        ]
        db.execute(insert(House), houses)
        db.execute(
            insert(HouseOwner),
            [
                {
                    "id": new_id(),
                    "house_id": house["id"],
                    "name": f"登记{index}",
                    "phone": "13800000000",
                    "created_at": now,
                    "updated_at": now,
                }
                for house in houses
                for index in range(2)
            ],
        )
        db.commit()
        for table in ("communities", "community_space_nodes", "houses", "house_owners"):
            db.execute(text(f"ANALYZE {table}"))
        repo = HousingRepository(db, company.id)
        community_id = community.id
        phase_id = phase.id
        captured: list[tuple[str, Any]] = []

        def record(
            conn: Any, cursor: Any, statement: str, parameters: Any, context: Any, executemany: bool
        ) -> None:
            captured.append((statement, parameters))

        connection = db.connection()
        event.listen(connection, "before_cursor_execute", record)
        try:
            page, total = repo.houses(
                community_id, page=1, page_size=20, sort="-created_at", external_code="X0000-001"
            )
        finally:
            event.remove(connection, "before_cursor_execute", record)
        assert len(captured) == 1 and total == 1 and len(page) == 1
        statement, parameters = captured[0]
        selective: dict[str, Any] = connection.exec_driver_sql(
            f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {statement}", parameters
        ).scalar_one()[0]
        assert "ix_house_community_external" in json.dumps(selective)

        captured.clear()
        event.listen(connection, "before_cursor_execute", record)
        try:
            page, total = repo.houses(
                community_id, page=9999, page_size=20, sort="-created_at", space_node_id=phase_id
            )
        finally:
            event.remove(connection, "before_cursor_execute", record)
        assert len(captured) == 1 and total == 25000 and page == []
        statement, parameters = captured[0]
        subtree: dict[str, Any] = connection.exec_driver_sql(
            f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {statement}", parameters
        ).scalar_one()[0]
        assert "Recursive Union" in json.dumps(subtree)
        assert subtree["Plan"]["Actual Rows"] == 1
        print(
            "Housing plans: 551 nodes / 25000 houses / 50000 owners; "
            f"selective={selective['Execution Time']}ms, "
            f"empty subtree page={subtree['Execution Time']}ms"
        )
