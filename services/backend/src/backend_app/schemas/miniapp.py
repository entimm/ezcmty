from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import (
    ConfigDict,
    Field,
    StringConstraints,
    TypeAdapter,
    WithJsonSchema,
    model_validator,
)

from backend_app.schemas.admin import AdminSchema, Identifier
from backend_app.schemas.housing import Phone

RowVersion = Annotated[int, Field(ge=1, le=9007199254740991)]
IdempotencyKey = Annotated[
    str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]{1,128}$")
]
WechatCode = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=512)]
_identifier_schema = TypeAdapter(Identifier).json_schema()
ClientIdentityId = Annotated[
    Literal["resident"] | Identifier,
    WithJsonSchema({"oneOf": [{"type": "string", "const": "resident"}, _identifier_schema]}),
]


class MiniappLogin(AdminSchema):
    code: WechatCode


class PhoneBindingCreate(MiniappLogin):
    expected_phone: Phone | None = None


class MiniappUser(AdminSchema):
    id: Identifier
    enabled: bool
    created_at: datetime
    last_login_at: datetime


class ClientSession(AdminSchema):
    token: str
    expires_at: datetime
    user: MiniappUser


class ClientSessionState(AdminSchema):
    expires_at: datetime
    user: MiniappUser


class PhoneBinding(AdminSchema):
    id: Identifier
    phone: str
    status: Literal["active", "unbound"]
    first_verified_at: datetime
    last_verified_at: datetime
    unbound_at: datetime | None
    row_version: RowVersion
    created_at: datetime
    updated_at: datetime


class PhoneBindingPage(AdminSchema):
    items: list[PhoneBinding]
    total: int
    page: int
    page_size: int


class ClientIdentity(AdminSchema):
    model_config = ConfigDict(
        json_schema_extra={
            "oneOf": [
                {
                    "properties": {
                        "id": {"const": "resident"},
                        "type": {"const": "resident"},
                        "display_name": {"const": "居民"},
                    }
                },
                {
                    "properties": {
                        "id": _identifier_schema,
                        "type": {"not": {"const": "resident"}},
                    }
                },
            ]
        }
    )
    id: ClientIdentityId
    type: Annotated[str, Field(min_length=1, max_length=32, pattern=r"^[a-z][a-z0-9_]{0,31}$")]
    display_name: Annotated[str, Field(min_length=1, max_length=160)]

    @model_validator(mode="after")
    def validate_identity(self) -> ClientIdentity:
        if self.id == "resident":
            if self.type != "resident" or self.display_name != "居民":
                raise ValueError("Invalid derived resident identity")
        elif self.type == "resident":
            raise ValueError("Resident identity cannot reference an association")
        return self


class ClientIdentityPage(AdminSchema):
    items: list[ClientIdentity]
    total: Annotated[int, Field(ge=1, le=9007199254740991)]
    page: Annotated[int, Field(ge=1, le=9007199254740991)]
    page_size: Annotated[int, Field(ge=1, le=100)]
