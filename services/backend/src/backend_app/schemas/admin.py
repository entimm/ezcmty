from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator

from backend_app.core.identifiers import UUID_PATTERN, normalize_uuid
from backend_app.domain.admin.types import AdminScope as AdminScope

Name = Annotated[str, Field(min_length=1, max_length=80)]
Identifier = Annotated[
    str,
    Field(min_length=36, max_length=36, pattern=UUID_PATTERN, json_schema_extra={"format": "uuid"}),
    AfterValidator(normalize_uuid),
]
Password = Annotated[str, Field(min_length=12, max_length=128)]


class AdminSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True, hide_input_in_errors=True)


class AdminLogin(AdminSchema):
    login_name: Annotated[
        str, Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.@-]*$")
    ]
    password: Annotated[str, Field(min_length=1, max_length=128)]


class PasswordChange(AdminSchema):
    current_password: Annotated[str, Field(min_length=1, max_length=128)]
    new_password: Password


class PasswordReset(AdminSchema):
    password: Password


class ProfileUpdate(AdminSchema):
    display_name: Name


class AccountCreate(AdminSchema):
    login_name: Annotated[
        str, Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.@-]*$")
    ]
    display_name: Name
    password: Password
    role_ids: list[Identifier] = Field(default_factory=list)


class AccountUpdate(AdminSchema):
    display_name: Name | None = None
    enabled: bool | None = None


class RoleSet(AdminSchema):
    role_ids: list[Identifier]


class RoleCreate(AdminSchema):
    code: Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")]
    name: Name


class RoleUpdate(AdminSchema):
    name: Name | None = None
    enabled: bool | None = None


class PermissionSet(AdminSchema):
    permissions: list[Annotated[str, Field(min_length=1, max_length=100)]]


class AdminSession(AdminSchema):
    scope: AdminScope
    subject_id: Identifier
    login_name: str
    display_name: str
    permissions: list[str]
    must_change_password: bool
    csrf_token: str


class AdminProfile(AdminSchema):
    id: Identifier
    scope: AdminScope
    login_name: str
    display_name: str


class RoleSummary(AdminSchema):
    id: Identifier
    code: str
    name: str
    enabled: bool
    is_system: bool


class AdminAccount(AdminSchema):
    id: Identifier
    scope: AdminScope
    login_name: str
    display_name: str
    enabled: bool
    must_change_password: bool
    created_at: datetime
    roles: list[RoleSummary]

    @field_validator("created_at")
    @classmethod
    def normalize_time(cls, value: datetime) -> datetime:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class AdminRole(RoleSummary):
    permissions: list[str]


class AdminPermission(AdminSchema):
    code: str
    name: str
    group: str
    assignable: bool


class AuditEntry(AdminSchema):
    id: Identifier
    property_company_id: Identifier | None
    actor_id: Identifier | None
    actor_name: str | None
    action: str
    target_type: str
    target_id: Identifier | None
    result: Literal["success", "failure"]
    request_id: str
    created_at: datetime
    metadata: dict[str, Any]

    @field_validator("created_at")
    @classmethod
    def normalize_time(cls, value: datetime) -> datetime:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class AccountPage(AdminSchema):
    items: list[AdminAccount]
    total: int
    page: int
    page_size: int


class RolePage(AdminSchema):
    items: list[AdminRole]
    total: int
    page: int
    page_size: int


class AuditPage(AdminSchema):
    items: list[AuditEntry]
    total: int
    page: int
    page_size: int
