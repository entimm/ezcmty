from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from backend_app.core.errors import AppError
from backend_app.repositories.housing import HousingRepository

SpaceType = Literal["phase", "building", "unit"]


def effective_enabled(community_enabled: bool, path_states: Iterable[bool]) -> bool:
    return community_enabled and all(path_states)


def is_valid_space_parent(node_type: SpaceType, parent_type: str | None) -> bool:
    parents: dict[SpaceType, set[str | None]] = {
        "phase": {None},
        "building": {None, "phase"},
        "unit": {"building"},
    }
    return parent_type in parents[node_type]


def normalize_owner_phone(value: object) -> object:
    if not isinstance(value, str):
        return value
    value = value.strip()
    for prefix in ("+86", "0086"):
        if value.startswith(prefix):
            return value[len(prefix) :]
    return value


def normalize_external_code(value: object) -> object:
    return (value.strip() or None) if isinstance(value, str) else value


@dataclass(frozen=True)
class HouseLocation:
    phase_name: str | None = None
    building_name: str = ""
    unit_name: str | None = None
    room_no: str = ""
    house_external_code: str | None = None

    def __post_init__(self) -> None:
        for field, limit in (
            ("phase_name", 80),
            ("building_name", 80),
            ("unit_name", 80),
            ("room_no", 32),
            ("house_external_code", 64),
        ):
            value = getattr(self, field)
            if value is not None and not isinstance(value, str):
                raise AppError("property.house_location_invalid")
            value = value.strip() if value is not None else ""
            if len(value) > limit or (field in {"building_name", "room_no"} and not value):
                raise AppError("property.house_location_invalid")
            object.__setattr__(self, field, value or None)


def house_location_snapshot(
    repo: HousingRepository,
    community_id: str,
    house_id: str,
    *,
    house_external_code: str | None = None,
    lock: bool = False,
    exclusive: bool = False,
) -> dict[str, Any]:
    community = repo.community(community_id)
    house, path = repo.house_path(community_id, house_id, lock=lock, exclusive=exclusive)
    if community is None or house is None or not path:
        raise AppError("resource.not_found")
    kinds = [node.node_type for node in path]
    if (
        kinds
        not in (
            ["building"],
            ["phase", "building"],
            ["building", "unit"],
            ["phase", "building", "unit"],
        )
        or path[0].parent_id is not None
        or any(child.parent_id != parent.id for parent, child in zip(path, path[1:], strict=False))
        or house.space_node_id != path[-1].id
    ):
        raise AppError("property.house_location_invalid")
    if house_external_code is not None and house.external_code != house_external_code:
        raise AppError("property.house_external_code_mismatch")
    return {
        "house_id": house.id,
        "community_id": community.id,
        "community_name": community.name,
        "space_node_id": house.space_node_id,
        "path": [
            {"id": node.id, "node_type": node.node_type, "name": node.name, "enabled": node.enabled}
            for node in path
        ],
        "room_no": house.room_no,
        "house_external_code": house_external_code,
        "external_code": house.external_code,
        "community_enabled": community.enabled,
        "house_enabled": house.enabled,
        "effective_enabled": effective_enabled(
            community.enabled, [house.enabled, *(node.enabled for node in path)]
        ),
    }


def resolve_house_location(
    repo: HousingRepository, community_id: str, location: HouseLocation
) -> dict[str, Any]:
    """Resolve direct parent/child identities; optional levels are never wildcards."""
    if repo.community(community_id) is None:
        raise AppError("resource.not_found")
    parent_id = None
    for kind, name in (
        ("phase", location.phase_name),
        ("building", location.building_name),
        ("unit", location.unit_name),
    ):
        if name is None:
            continue
        nodes = repo.location_nodes(community_id, parent_id, kind, name)
        if len(nodes) != 1:
            raise AppError("property.house_location_invalid")
        parent_id = nodes[0].id
    if parent_id is None:
        raise AppError("property.house_location_invalid")
    houses = repo.location_houses(community_id, parent_id, location.room_no)
    if len(houses) != 1:
        raise AppError("property.house_location_invalid")
    return house_location_snapshot(
        repo,
        community_id,
        houses[0].id,
        house_external_code=location.house_external_code,
    )


def revalidate_house_location(
    repo: HousingRepository,
    community_id: str,
    snapshot: Mapping[str, Any],
    *,
    lock: bool = False,
    exclusive: bool = False,
) -> dict[str, Any]:
    """Recheck the original identity, including names; never resolve its old address again."""
    if snapshot.get("community_id") != community_id or not isinstance(
        snapshot.get("house_id"), str
    ):
        raise AppError("property.house_location_changed")
    try:
        current = house_location_snapshot(
            repo,
            community_id,
            snapshot["house_id"],
            house_external_code=snapshot.get("house_external_code"),
            lock=lock,
            exclusive=exclusive,
        )
    except AppError as error:
        if error.code in {
            "resource.not_found",
            "property.house_location_invalid",
            "property.house_external_code_mismatch",
        }:
            raise AppError("property.house_location_changed") from error
        raise
    for key in ("house_id", "community_id", "space_node_id", "room_no"):
        if current[key] != snapshot.get(key):
            raise AppError("property.house_location_changed")
    expected_path = snapshot.get("path")
    if (
        not isinstance(expected_path, list)
        or not all(isinstance(node, dict) for node in expected_path)
        or [
            {key: node.get(key) for key in ("id", "node_type", "name")}
            for node in expected_path
            if isinstance(node, dict)
        ]
        != [{key: node[key] for key in ("id", "node_type", "name")} for node in current["path"]]
    ):
        raise AppError("property.house_location_changed")
    return current
