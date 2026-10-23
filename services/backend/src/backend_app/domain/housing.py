import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from typing import Any, Literal, cast

from backend_app.core.errors import AppError
from backend_app.core.identifiers import new_id, normalize_uuid
from backend_app.models.admin import utc_now
from backend_app.models.housing import House, HouseOwner
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
class SpaceLocation:
    phase_name: str | None = None
    building_name: str = ""
    unit_name: str | None = None

    def __post_init__(self) -> None:
        for field in ("phase_name", "building_name", "unit_name"):
            value = getattr(self, field)
            if value is not None and not isinstance(value, str):
                raise AppError("property.house_location_invalid")
            value = value.strip() if value is not None else ""
            if len(value) > 80 or (field == "building_name" and not value):
                raise AppError("property.house_location_invalid")
            object.__setattr__(self, field, value or None)


def space_location_snapshot(
    repo: HousingRepository, community_id: str, node_id: str, *, lock: bool = False
) -> dict[str, Any]:
    community = repo.community(community_id)
    path = repo.space_path(community_id, node_id, lock=lock, exclusive=True)
    if community is None or not path:
        raise AppError("resource.not_found")
    if (
        [node.node_type for node in path]
        not in (
            ["building"],
            ["phase", "building"],
            ["building", "unit"],
            ["phase", "building", "unit"],
        )
        or path[0].parent_id is not None
        or path[-1].id != node_id
        or any(child.parent_id != parent.id for parent, child in zip(path, path[1:], strict=False))
    ):
        raise AppError("property.invalid_house_parent")
    return {
        "community_id": community.id,
        "community_name": community.name,
        "space_node_id": node_id,
        "path": [
            {"id": node.id, "node_type": node.node_type, "name": node.name, "enabled": node.enabled}
            for node in path
        ],
        "effective_enabled": effective_enabled(community.enabled, (node.enabled for node in path)),
    }


def resolve_space_location(
    repo: HousingRepository, community_id: str, location: SpaceLocation
) -> dict[str, Any]:
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
            raise AppError(
                "property.house_location_invalid",
                public_detail="空间路径不存在或不匹配，请先建立分区、楼栋和单元",
            )
        parent_id = nodes[0].id
    assert parent_id is not None
    return space_location_snapshot(repo, community_id, parent_id)


def _path_identity(snapshot: Mapping[str, Any]) -> list[dict[str, Any]]:
    path = snapshot.get("path")
    if not isinstance(path, list) or not path or not all(isinstance(node, dict) for node in path):
        raise AppError("property.house_location_changed")
    return [{key: node.get(key) for key in ("id", "node_type", "name")} for node in path]


def revalidate_space_location(
    repo: HousingRepository, community_id: str, snapshot: Mapping[str, Any], *, lock: bool = False
) -> dict[str, Any]:
    if snapshot.get("community_id") != community_id or not isinstance(
        snapshot.get("space_node_id"), str
    ):
        raise AppError("property.house_location_changed")
    try:
        current = space_location_snapshot(repo, community_id, snapshot["space_node_id"], lock=lock)
    except AppError as error:
        if error.code in {"resource.not_found", "property.invalid_house_parent"}:
            raise AppError("property.house_location_changed") from error
        raise
    if _path_identity(current) != _path_identity(snapshot):
        raise AppError("property.house_location_changed")
    return current


@dataclass(frozen=True)
class HouseLocation:
    phase_name: str | None = None
    building_name: str = ""
    unit_name: str | None = None
    room_no: str = ""
    house_external_code: str | None = None

    def __post_init__(self) -> None:
        space = SpaceLocation(self.phase_name, self.building_name, self.unit_name)
        for field, value in asdict(space).items():
            object.__setattr__(self, field, value)
        for field, limit in (("room_no", 32), ("house_external_code", 64)):
            value = getattr(self, field)
            if value is not None and not isinstance(value, str):
                raise AppError("property.house_location_invalid")
            value = value.strip() if value is not None else ""
            if len(value) > limit or (field == "room_no" and not value):
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
    space = resolve_space_location(
        repo,
        community_id,
        SpaceLocation(location.phase_name, location.building_name, location.unit_name),
    )
    houses = repo.location_houses(community_id, space["space_node_id"], location.room_no)
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
    if _path_identity(current) != _path_identity(snapshot):
        raise AppError("property.house_location_changed")
    return current


def _creation_text(value: object, limit: int, *, required: bool = False) -> str | None:
    if value is not None and not isinstance(value, str):
        raise AppError("VALIDATION_ERROR")
    value = value.strip() if isinstance(value, str) else ""
    if len(value) > limit or required and not value:
        raise AppError("VALIDATION_ERROR")
    return value or None


@dataclass(frozen=True)
class InitialHouseOwner:
    name: str
    phone: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _creation_text(self.name, 80, required=True))
        phone = normalize_owner_phone(self.phone)
        if not isinstance(phone, str) or re.fullmatch(r"1[3-9][0-9]{9}", phone) is None:
            raise AppError("VALIDATION_ERROR")
        object.__setattr__(self, "phone", phone)


def house_creation_identity(space_node_id: str, room_no: str) -> dict[str, str]:
    try:
        if not isinstance(space_node_id, str):
            raise ValueError
        node_id = normalize_uuid(space_node_id)
    except ValueError:
        raise AppError("VALIDATION_ERROR") from None
    return {
        "space_node_id": node_id,
        "room_no": cast(str, _creation_text(room_no, 32, required=True)),
    }


@dataclass(frozen=True)
class HouseCreationCommand:
    space_node_id: str
    room_no: str
    floor_no: int | None = None
    external_code: str | None = None
    owners: tuple[InitialHouseOwner, ...] = ()

    def __post_init__(self) -> None:
        for key, value in house_creation_identity(self.space_node_id, self.room_no).items():
            object.__setattr__(self, key, value)
        if self.floor_no is not None and (
            type(self.floor_no) is not int or not -32768 <= self.floor_no <= 32767
        ):
            raise AppError("VALIDATION_ERROR")
        object.__setattr__(self, "external_code", _creation_text(self.external_code, 64))
        if not isinstance(self.owners, tuple) or not all(
            isinstance(owner, InitialHouseOwner) for owner in self.owners
        ):
            raise AppError("VALIDATION_ERROR")
        if len(set(self.owners)) != len(self.owners):
            raise AppError("property.duplicate_house_owner")

    @classmethod
    def from_input(cls, value: Mapping[str, Any]) -> HouseCreationCommand:
        if set(value) - {"space_node_id", "room_no", "floor_no", "external_code", "owners"}:
            raise AppError("VALIDATION_ERROR")
        data = dict(value)
        owners = data.get("owners", ())
        if not isinstance(owners, (list, tuple)) or not all(
            isinstance(owner, Mapping) for owner in owners
        ):
            raise AppError("VALIDATION_ERROR")
        try:
            data["owners"] = tuple(InitialHouseOwner(**owner) for owner in owners)
            return cls(**data)
        except TypeError:
            raise AppError("VALIDATION_ERROR") from None

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "owners": [asdict(owner) for owner in self.owners]}

    def content(self) -> dict[str, Any]:
        return {
            "space_node_id": self.space_node_id,
            "room_no": self.room_no,
            "floor_no": self.floor_no,
            "external_code": self.external_code,
        }

    def fingerprint(self) -> str:
        return hashlib.sha256(
            json.dumps(
                self.content(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ).encode()
        ).hexdigest()


def house_creation_permissions(*, has_owners: bool = False) -> frozenset[str]:
    return frozenset(
        {"property.house.create", *({"property.house_owner.create"} if has_owners else set())}
    )


def inspect_house_creation(
    repo: HousingRepository,
    community_id: str,
    command: HouseCreationCommand,
    *,
    target_id: str | None = None,
    lock: bool = False,
) -> House | None:
    if target_id is not None:
        target = repo.house(community_id, target_id, lock=lock)
        if (
            target is None
            or target.space_node_id != command.space_node_id
            or target.room_no != command.room_no
        ):
            raise AppError("property.house_location_changed")
        candidates = [target]
    else:
        candidates = repo.location_houses(community_id, command.space_node_id, command.room_no)
        if lock and len(candidates) == 1:
            target = repo.house(community_id, candidates[0].id, lock=True)
            candidates = [target] if target else []
    if not candidates:
        return None
    if len(candidates) != 1 or any(
        getattr(candidates[0], key) != value for key, value in command.content().items()
    ):
        raise AppError("property.duplicate_room_no")
    return candidates[0]


def create_house_records(
    repo: HousingRepository, community_id: str, command: HouseCreationCommand
) -> tuple[House, list[HouseOwner]]:
    now = utc_now()
    house = House(
        id=new_id(),
        community_id=community_id,
        **command.content(),
        enabled=True,
        created_at=now,
        updated_at=now,
    )
    repo.db.add(house)
    repo.db.flush()
    owners = [
        HouseOwner(
            id=new_id(),
            house_id=house.id,
            name=item.name,
            phone=item.phone,
            enabled=True,
            created_at=now,
            updated_at=now,
        )
        for item in command.owners
    ]
    repo.db.add_all(owners)
    return house, owners
