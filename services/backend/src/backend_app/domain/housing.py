from collections.abc import Iterable
from typing import Literal

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
