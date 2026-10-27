import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Annotated, Any, Protocol

from pydantic import ConfigDict, Field, TypeAdapter
from pydantic.dataclasses import dataclass as validated_dataclass

_CONFIG = ConfigDict(
    strict=True,
    revalidate_instances="always",
    extra="forbid",
    allow_inf_nan=False,
    hide_input_in_errors=True,
    regex_engine="python-re",
)
_Key = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}\z")]
_Nonempty = Annotated[str, Field(min_length=1)]
_Scalar = str | int | float | bool | None
_Scope = Annotated[str, Field(pattern=r"^(company|community)\z")]
_Actor = Annotated[str, Field(pattern=r"^(platform_admin|property_admin)\z")]
_Normalization = Annotated[str, Field(pattern=r"^(trim|lowercase|uppercase)\z")]


@dataclass(frozen=True)
class ImportField:
    # Validate fields at the definition boundary, including existing dataclass instances.
    __pydantic_config__ = _CONFIG

    key: _Key
    label: Annotated[str, Field(min_length=1, pattern=r"^[^\x00-\x1f]*\z")]
    order: Annotated[int, Field(gt=0)]
    required: bool = False
    data_type: Annotated[
        str, Field(pattern=r"^(string|integer|decimal|boolean|date|datetime)\z")
    ] = "string"
    max_length: Annotated[int, Field(gt=0)] | None = None
    format: (
        Annotated[str, Field(pattern=r"^(email|phone|mobile|uuid|date|date-time|datetime)\z")]
        | None
    ) = None
    enum_values: tuple[_Scalar, ...] = ()
    example: _Scalar = None
    description: str = ""
    normalization_rules: tuple[_Normalization, ...] = ()
    sensitive: bool = False


@validated_dataclass(frozen=True, config=_CONFIG)
class ImportDefinition:
    key: _Key
    name: _Nonempty
    version_no: Annotated[int, Field(gt=0)]
    adapter_key: _Nonempty
    fields: Annotated[tuple[ImportField, ...], Field(min_length=1, max_length=200)]
    allowed_scope_types: Annotated[tuple[_Scope, ...], Field(min_length=1)] = (
        "company",
        "community",
    )
    supported_modes: tuple[Annotated[str, Field(pattern=r"^create\z")]] = ("create",)
    allowed_actor_scopes: Annotated[tuple[_Actor, ...], Field(min_length=1)] = (
        "platform_admin",
        "property_admin",
    )
    required_permissions: tuple[str, ...] = ()
    read_permissions: tuple[str, ...] = ()
    available_for_new_batches: bool = True
    template_downloadable: bool = True
    released_at: str = ""
    release_notes: str = ""
    sheet_name: Annotated[str, Field(min_length=1, max_length=31)] = "导入数据"

    def __post_init__(self) -> None:
        keys: set[str] = set()
        labels: set[str] = set()
        orders: set[int] = set()
        for definition in self.fields:
            if definition.key in keys or definition.order in orders or definition.label in labels:
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


_DEFINITION_ADAPTER = TypeAdapter(ImportDefinition)


def definition_from_mapping(value: Mapping[str, Any]) -> ImportDefinition:
    # JSON mode accepts arrays as tuples while retaining strict scalar validation.
    return _DEFINITION_ADAPTER.validate_json(json.dumps(dict(value), allow_nan=False))
