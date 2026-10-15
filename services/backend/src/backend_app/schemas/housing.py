from datetime import UTC, datetime
from typing import Annotated, Any, Self, cast

from pydantic import (
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    WithJsonSchema,
    field_validator,
    model_validator,
)

from backend_app.domain.housing import (
    SpaceType,
    normalize_external_code,
    normalize_owner_phone,
)
from backend_app.schemas.admin import AdminSchema, Identifier

SpaceName = Annotated[
    str, StringConstraints(strip_whitespace=True), Field(min_length=1, max_length=80)
]
RoomNo = Annotated[
    str, StringConstraints(strip_whitespace=True), Field(min_length=1, max_length=32)
]
ExternalCode = Annotated[
    Annotated[str, Field(max_length=64)] | None, BeforeValidator(normalize_external_code)
]
Phone = Annotated[
    str,
    StringConstraints(min_length=11, max_length=11, pattern=r"^1[3-9][0-9]{9}$"),
    BeforeValidator(normalize_owner_phone),
    WithJsonSchema(
        {
            "type": "string",
            "minLength": 11,
            "maxLength": 15,
            "pattern": r"^(?:(?:\+86|0086))?1[3-9][0-9]{9}$",
        }
    ),
]
Floor = Annotated[int, Field(ge=-32768, le=32767)]
SortOrder = Annotated[int, Field(ge=0, le=2147483647)]


def _remove_default(schema: dict[str, Any]) -> None:
    schema.pop("default", None)


class HousingUpdate(AdminSchema):
    model_config = ConfigDict(json_schema_extra={"minProperties": 1})

    @model_validator(mode="after")
    def require_changes(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("At least one field is required")
        return self


class SpaceNodeCreate(AdminSchema):
    parent_id: Identifier | None = None
    node_type: SpaceType
    name: SpaceName
    external_code: ExternalCode = None
    sort_order: SortOrder = 0


class SpaceNodeUpdate(HousingUpdate):
    name: SpaceName = Field(default=cast(Any, None), json_schema_extra=_remove_default)
    external_code: ExternalCode = None
    sort_order: SortOrder = Field(default=cast(Any, None), json_schema_extra=_remove_default)
    enabled: bool = Field(default=cast(Any, None), json_schema_extra=_remove_default)


class HouseOwnerCreate(AdminSchema):
    name: SpaceName
    phone: Phone


class HouseOwnerUpdate(HousingUpdate):
    name: SpaceName = Field(default=cast(Any, None), json_schema_extra=_remove_default)
    phone: Phone = Field(default=cast(Any, None), json_schema_extra=_remove_default)
    enabled: bool = Field(default=cast(Any, None), json_schema_extra=_remove_default)


class HouseCreate(AdminSchema):
    space_node_id: Identifier
    room_no: RoomNo
    floor_no: Floor | None = None
    external_code: ExternalCode = None
    owners: list[HouseOwnerCreate] = Field(default_factory=list)


class HouseUpdate(HousingUpdate):
    room_no: RoomNo = Field(default=cast(Any, None), json_schema_extra=_remove_default)
    floor_no: Floor | None = None
    external_code: ExternalCode = None
    enabled: bool = Field(default=cast(Any, None), json_schema_extra=_remove_default)


class HousingRecord(AdminSchema):
    id: Identifier
    enabled: bool
    effective_enabled: bool
    created_at: datetime
    updated_at: datetime

    @field_validator("created_at", "updated_at")
    @classmethod
    def normalize_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Timestamp must include a timezone")
        return value.astimezone(UTC)


class SpaceAncestor(AdminSchema):
    id: Identifier
    node_type: SpaceType
    name: str


class SpaceNode(HousingRecord):
    community_id: Identifier
    parent_id: Identifier | None
    node_type: SpaceType
    name: str
    external_code: str | None
    sort_order: int
    has_children: bool
    ancestors: list[SpaceAncestor]


class House(HousingRecord):
    community_id: Identifier
    space_node_id: Identifier
    room_no: str
    floor_no: int | None
    external_code: str | None
    display_address: str


class HouseOwner(HousingRecord):
    house_id: Identifier
    name: str
    phone: str


class SpaceNodePage(AdminSchema):
    items: list[SpaceNode]
    total: int
    page: int
    page_size: int


class HousePage(AdminSchema):
    items: list[House]
    total: int
    page: int
    page_size: int


class HouseOwnerPage(AdminSchema):
    items: list[HouseOwner]
    total: int
    page: int
    page_size: int
