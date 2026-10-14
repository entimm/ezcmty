from dataclasses import dataclass
from typing import Literal

AdminScope = Literal["platform_admin", "property_admin"]


@dataclass(frozen=True)
class AdminAuthorization:
    account_id: str
    version: int
    permissions: list[str]
    must_change_password: bool
    scope: AdminScope
    property_company_id: str | None
