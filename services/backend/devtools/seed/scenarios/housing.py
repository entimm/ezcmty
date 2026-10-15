from devtools.seed.runtime import Actor, Executor
from devtools.seed.scenarios.property import Company


def populate(
    executor: Executor, actor: Actor, company: Company, parameters: dict[str, int]
) -> None:
    def node(key: str, community: str, kind: str, name: str, parent: str | None = None) -> str:
        values = {"node_type": kind, "name": name, "parent_id": parent}
        identity = {"community_id": community, **values}
        return executor.step(
            key,
            actor,
            "property.space.create",
            "node",
            values,
            refs={"community_id": community},
            unique=identity,
            expected={**identity, "enabled": True},
        )

    def disable(
        key: str, model: str, action: str, identifier: str, community: str, house: str | None = None
    ) -> None:
        refs = {"community_id": community}
        if house:
            refs["house_id"] = house
        executor.step(
            key + "/disable",
            actor,
            action,
            model,
            {"enabled": False},
            identifier=identifier,
            refs=refs,
            expected={"enabled": False},
        )

    def houses(key: str, community: str, parent: str, count: int) -> None:
        for number in range(count):
            house_key = key + f"/house/{number}"
            values = {
                "space_node_id": parent,
                "room_no": str(number + 1),
                "floor_no": number % 30 + 1,
            }
            house = executor.step(
                house_key,
                actor,
                "property.house.create",
                "house",
                values,
                refs={"community_id": community},
                unique={"space_node_id": parent, "room_no": str(number + 1)},
                expected={**values, "community_id": community, "enabled": True},
            )
            for owner_number in range(parameters["owners_per_house"]):
                owner_key = house_key + f"/owner/{owner_number}"
                owner_values = {
                    "name": f"演示业主 {owner_number + 1}",
                    "phone": f"139{owner_number:08d}",
                }
                identity = {"house_id": house, **owner_values}
                owner = executor.step(
                    owner_key,
                    actor,
                    "property.house_owner.create",
                    "owner",
                    owner_values,
                    refs={"community_id": community, "house_id": house},
                    unique=identity,
                    expected={**identity, "enabled": True},
                )
                if owner_number > 0 and owner_number == parameters["owners_per_house"] - 1:
                    disable(
                        owner_key, "owner", "property.house_owner.update", owner, community, house
                    )
            if count > 1 and number == count - 1:
                disable(house_key, "house", "property.house.update", house, community)

    for community_number, community in enumerate(company.communities):
        key = f"housing/{company.index}/{community_number}"
        phases = [
            node(key + f"/phase/{i}", community, "phase", f"第 {i + 1} 期")
            for i in range(parameters["phases_per_community"])
        ]
        for building_number in range(parameters["buildings_per_community"]):
            building_key = key + f"/building/{building_number}"
            # Exercise both root buildings and phase buildings without changing total counts.
            parent = (
                phases[(building_number // 2) % len(phases)]
                if phases and building_number % 2
                else None
            )
            building = node(
                building_key, community, "building", f"{building_number + 1} 号楼", parent
            )
            houses(building_key, community, building, parameters["houses_per_building"])
            for unit_number in range(parameters["units_per_building"]):
                unit_key = building_key + f"/unit/{unit_number}"
                unit = node(unit_key, community, "unit", f"{unit_number + 1} 单元", building)
                houses(unit_key, community, unit, parameters["houses_per_unit"])
                if unit_number > 0 and unit_number == parameters["units_per_building"] - 1:
                    disable(unit_key, "node", "property.space.update", unit, community)
            if building_number > 0 and building_number == parameters["buildings_per_community"] - 1:
                disable(building_key, "node", "property.space.update", building, community)
        if phases:
            disable(key + "/phase/last", "node", "property.space.update", phases[-1], community)
