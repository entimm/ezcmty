from datetime import datetime
from typing import Annotated, Literal

from pydantic import StringConstraints

from backend_app.schemas.admin import AdminSchema, Identifier
from backend_app.schemas.miniapp import RowVersion

ClaimStatus = Literal["pending", "approved", "rejected", "cancelled"]
BindingStatus = Literal["active", "released", "revoked"]
MatchStatus = Literal["matched", "unmatched"]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]


class HouseClaimCreate(AdminSchema):
    house_id: Identifier
    applicant_name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)
    ]
    phone_binding_id: Identifier
    applicant_remark: Reason | None = None


class ClaimCancellation(AdminSchema):
    expected_row_version: RowVersion


class ClaimReview(ClaimCancellation):
    decision: Literal["approved", "rejected"]
    reason: Reason | None = None


class HouseRelease(ClaimCancellation):
    reason: Reason | None = None


class HouseRevocation(ClaimCancellation):
    reason: Reason


class ResidentHouseClaim(AdminSchema):
    id: Identifier
    community_id: Identifier
    house_id: Identifier
    house_label_snapshot: str
    applicant_name: str
    applicant_phone: str
    applicant_remark: str | None
    status: ClaimStatus
    review_reason: str | None
    reviewed_at: datetime | None
    cancelled_at: datetime | None
    row_version: RowVersion
    created_at: datetime
    updated_at: datetime


class PropertyHouseClaim(ResidentHouseClaim):
    property_company_id: Identifier
    user_id: Identifier
    match_status: MatchStatus
    matched_owner_id: Identifier | None
    reviewed_by_admin_id: Identifier | None


class ResidentHouseBinding(AdminSchema):
    id: Identifier
    community_id: Identifier
    house_id: Identifier
    claim_application_id: Identifier
    house_label_snapshot: str
    status: BindingStatus
    effective_enabled: bool
    granted_at: datetime
    ended_at: datetime | None
    end_reason: str | None
    row_version: RowVersion
    created_at: datetime
    updated_at: datetime


class PropertyHouseBinding(ResidentHouseBinding):
    property_company_id: Identifier
    user_id: Identifier
    applicant_name: str
    applicant_phone: str


class ClaimableCommunity(AdminSchema):
    id: Identifier
    name: str
    address: str


class ClaimableSpaceNode(AdminSchema):
    id: Identifier
    community_id: Identifier
    parent_id: Identifier | None
    name: str
    node_type: Literal["phase", "building", "unit"]
    has_children: bool


class ClaimableHouse(AdminSchema):
    id: Identifier
    community_id: Identifier
    space_node_id: Identifier
    room_no: str
    display_address: str


class Page[T](AdminSchema):
    items: list[T]
    total: int
    page: int
    page_size: int


class ResidentHouseClaimPage(Page[ResidentHouseClaim]):
    pass


class PropertyHouseClaimPage(Page[PropertyHouseClaim]):
    pass


class ResidentHouseBindingPage(Page[ResidentHouseBinding]):
    pass


class PropertyHouseBindingPage(Page[PropertyHouseBinding]):
    pass


class ClaimableCommunityPage(Page[ClaimableCommunity]):
    pass


class ClaimableSpaceNodePage(Page[ClaimableSpaceNode]):
    pass


class ClaimableHousePage(Page[ClaimableHouse]):
    pass
