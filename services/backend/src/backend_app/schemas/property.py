from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, Field, StringConstraints, field_validator

from backend_app.core.identifiers import normalize_property_code
from backend_app.schemas.admin import (
    AdminAccount,
    AdminSchema,
    Identifier,
    LoginName,
    Name,
    Password,
)
from backend_app.schemas.billing import Month

Code = Annotated[
    str,
    Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$"),
    AfterValidator(normalize_property_code),
]
CompanyName = Annotated[
    str, StringConstraints(strip_whitespace=True), Field(min_length=1, max_length=160)
]
ContactName = Annotated[
    str, StringConstraints(strip_whitespace=True), Field(min_length=1, max_length=80)
]
ContactPhone = Annotated[
    str, StringConstraints(strip_whitespace=True), Field(min_length=1, max_length=32)
]
Address = Annotated[
    str, StringConstraints(strip_whitespace=True), Field(min_length=1, max_length=255)
]


class CompanyCreate(AdminSchema):
    code: Code
    name: CompanyName
    contact_name: ContactName | None = None
    contact_phone: ContactPhone | None = None


class CompanyUpdate(AdminSchema):
    name: CompanyName | None = None
    contact_name: ContactName | None = None
    contact_phone: ContactPhone | None = None
    enabled: bool | None = None


class PropertyCompany(AdminSchema):
    id: Identifier
    code: str
    name: str
    contact_name: str | None
    contact_phone: str | None
    enabled: bool
    created_at: datetime
    updated_at: datetime

    @field_validator("created_at", "updated_at")
    @classmethod
    def normalize_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Timestamp must include a timezone")
        return value.astimezone(UTC)


class PropertyWorkspaceSummary(AdminSchema):
    billing_month: Month
    pending_house_claims: Annotated[int, Field(ge=0)] | None
    monthly_receivable_cents: Annotated[int, Field(ge=0)] | None
    monthly_settled_cents: Annotated[int, Field(ge=0)] | None
    pending_reconciliation_count: Annotated[int, Field(ge=0)] | None


class CommunityCreate(AdminSchema):
    property_company_id: Identifier
    code: Code
    name: CompanyName
    address: Address


class CommunityUpdate(AdminSchema):
    name: CompanyName | None = None
    address: Address | None = None
    enabled: bool | None = None


class Community(AdminSchema):
    id: Identifier
    property_company_id: Identifier
    property_company_name: str
    code: str
    name: str
    address: str
    enabled: bool
    created_at: datetime
    updated_at: datetime

    @field_validator("created_at", "updated_at")
    @classmethod
    def normalize_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Timestamp must include a timezone")
        return value.astimezone(UTC)


class PropertyAdminCreate(AdminSchema):
    login_name: LoginName
    display_name: Name
    password: Password


class PropertyAdminAccount(AdminAccount):
    scope: Literal["property_admin"]
    property_company_id: Identifier


class CompanyPage(AdminSchema):
    items: list[PropertyCompany]
    total: int
    page: int
    page_size: int


class CommunityPage(AdminSchema):
    items: list[Community]
    total: int
    page: int
    page_size: int


class PropertyAdminPage(AdminSchema):
    items: list[PropertyAdminAccount]
    total: int
    page: int
    page_size: int
