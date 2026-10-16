from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, StringConstraints

from backend_app.schemas.admin import AdminSchema, Identifier
from backend_app.schemas.housing import Phone

RowVersion = Annotated[int, Field(ge=1, le=9007199254740991)]
IdempotencyKey = Annotated[
    str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]{1,128}$")
]
WechatCode = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=512)]


class MiniappLogin(AdminSchema):
    code: WechatCode


class PhoneBindingCreate(MiniappLogin):
    expected_phone: Phone | None = None


class MiniappUser(AdminSchema):
    id: Identifier
    enabled: bool
    created_at: datetime
    last_login_at: datetime


class ResidentSession(AdminSchema):
    token: str
    expires_at: datetime
    user: MiniappUser


class ResidentSessionState(AdminSchema):
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
