import re
from uuid import UUID, uuid7

UUID_PATTERN = (
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[47][0-9a-fA-F]{3}-"
    r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
)


def new_id() -> str:
    return str(uuid7())


def normalize_uuid(value: str) -> str:
    if re.fullmatch(UUID_PATTERN, value) is None:
        raise ValueError("Expected a hyphenated UUIDv4 or UUIDv7")
    return str(UUID(value))


def normalize_login_name(value: str) -> str:
    return value.lower()


def normalize_property_code(value: str) -> str:
    return value.upper()
