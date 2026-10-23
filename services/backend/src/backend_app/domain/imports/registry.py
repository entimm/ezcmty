import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ImportField:
    key: str
    label: str
    order: int
    required: bool = False
    data_type: str = "string"
    max_length: int | None = None
    format: str | None = None
    enum_values: tuple[Any, ...] = ()
    example: Any = None
    description: str = ""
    normalization_rules: tuple[str, ...] = ()
    sensitive: bool = False


@dataclass(frozen=True)
class ImportDefinition:
    key: str
    name: str
    version_no: int
    adapter_key: str
    fields: tuple[ImportField, ...]
    allowed_scope_types: tuple[str, ...] = ("company", "community")
    supported_modes: tuple[str, ...] = ("create",)
    allowed_actor_scopes: tuple[str, ...] = ("platform_admin", "property_admin")
    required_permissions: tuple[str, ...] = ()
    read_permissions: tuple[str, ...] = ()
    available_for_new_batches: bool = True
    template_downloadable: bool = True
    released_at: str = ""
    release_notes: str = ""
    sheet_name: str = "导入数据"

    def __post_init__(self) -> None:
        if (
            not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", self.key)
            or type(self.version_no) is not int
            or self.version_no < 1
            or not self.name
            or not self.adapter_key
            or not isinstance(self.fields, tuple)
            or not 1 <= len(self.fields) <= 200
            or not self.allowed_scope_types
            or not isinstance(self.allowed_scope_types, tuple)
            or set(self.allowed_scope_types) - {"company", "community"}
            or self.supported_modes != ("create",)
            or not self.allowed_actor_scopes
            or not isinstance(self.allowed_actor_scopes, tuple)
            or not isinstance(self.required_permissions, tuple)
            or not isinstance(self.read_permissions, tuple)
            or type(self.available_for_new_batches) is not bool
            or type(self.template_downloadable) is not bool
            or set(self.allowed_actor_scopes) - {"platform_admin", "property_admin"}
            or len(self.sheet_name) > 31
            or not self.sheet_name
        ):
            raise ValueError("Invalid import definition")
        keys: set[str] = set()
        labels: set[str] = set()
        orders: set[int] = set()
        for definition in self.fields:
            if (
                not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", definition.key)
                or definition.key in keys
                or definition.order in orders
                or type(definition.order) is not int
                or definition.order < 1
                or not definition.label
                or definition.label in labels
                or any(ord(character) < 32 for character in definition.label)
                or type(definition.required) is not bool
                or type(definition.sensitive) is not bool
                or not isinstance(definition.enum_values, tuple)
                or not isinstance(definition.normalization_rules, tuple)
                or any(
                    value is not None and not isinstance(value, (str, int, float, bool))
                    for value in (*definition.enum_values, definition.example)
                )
                or definition.data_type
                not in {"string", "integer", "decimal", "boolean", "date", "datetime"}
                or definition.max_length is not None
                and (type(definition.max_length) is not int or definition.max_length < 1)
                or definition.format is not None
                and definition.format
                not in {"email", "phone", "mobile", "uuid", "date", "date-time", "datetime"}
                or set(definition.normalization_rules) - {"trim", "lowercase", "uppercase"}
            ):
                raise ValueError("Invalid import field definition")
            keys.add(definition.key)
            labels.add(definition.label)
            orders.add(definition.order)
        if tuple(sorted(self.fields, key=lambda value: value.order)) != self.fields:
            raise ValueError("Import fields must be ordered")
        # Also reject non-JSON values and NaN in released configuration.
        json.dumps(asdict(self), allow_nan=False)

    @property
    def config_hash(self) -> str:
        configuration = asdict(self)
        if not self.read_permissions:
            configuration.pop("read_permissions")
        payload = json.dumps(
            configuration,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    @property
    def headers(self) -> tuple[str, ...]:
        return tuple(field.label for field in self.fields)


class ImportRegistry(Protocol):
    def get(
        self, key: str, version_no: int, config_hash: str | None = None
    ) -> ImportDefinition: ...

    def list(self) -> tuple[ImportDefinition, ...]: ...

    def get_adapter(self, adapter_key: str) -> Any: ...


def definition_from_mapping(value: Mapping[str, Any]) -> ImportDefinition:
    copied = dict(value)
    fields = copied.pop("fields", None)
    if not isinstance(fields, list):
        raise ValueError("Invalid import definition")
    definitions: list[ImportField] = []
    for item in fields:
        if not isinstance(item, dict):
            raise ValueError("Invalid import field definition")
        item = dict(item)
        for key in ("enum_values", "normalization_rules"):
            if key in item:
                if not isinstance(item[key], list):
                    raise ValueError("Invalid import field definition")
                item[key] = tuple(item[key])
        definitions.append(ImportField(**item))
    for key in (
        "allowed_scope_types",
        "supported_modes",
        "allowed_actor_scopes",
        "required_permissions",
        "read_permissions",
    ):
        if key in copied:
            if not isinstance(copied[key], list):
                raise ValueError("Invalid import definition")
            copied[key] = tuple(copied[key])
    return ImportDefinition(fields=tuple(definitions), **copied)
