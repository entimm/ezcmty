import json
from hashlib import sha256
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from backend_app.core.errors import AppError
from backend_app.core.identifiers import new_id
from backend_app.db.errors import is_unique_violation
from backend_app.domain.client.types import ClientAuthorization
from backend_app.domain.housing import SpaceType
from backend_app.models.house_claims import HouseClaim, ResidentHouseBinding
from backend_app.models.housing import House, SpaceNode
from backend_app.models.property import Community, PropertyCompany
from backend_app.repositories.house_claims import HouseClaimRepository
from backend_app.repositories.housing import HousingRepository
from backend_app.repositories.miniapp import MiniappRepository
from backend_app.repositories.pagination import page_statement, read_page
from backend_app.schemas import house_claims as schema
from backend_app.schemas.mappers.house_claims import resident_binding_view, resident_claim_view


class ResidentHouseClaimService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = HouseClaimRepository(db)
        self.identity = MiniappRepository(db)

    def create(
        self, ctx: ClientAuthorization, data: schema.HouseClaimCreate, key: str
    ) -> tuple[schema.ResidentHouseClaim, bool]:
        digest = sha256(json.dumps(data.model_dump(), sort_keys=True).encode()).hexdigest()
        try:
            self.identity.user(ctx.user_id, ctx.version)
            previous = self.repo.previous(ctx.user_id, key)
            if previous:
                if previous.request_fingerprint != digest:
                    raise AppError("resident.idempotency_conflict")
                return resident_claim_view(previous), False
            company, _, _, _ = self.repo.house(data.house_id)
            self.repo.company(company.id)
            self.identity.user(ctx.user_id, ctx.version, lock=True, exclusive=True)
            previous = self.repo.previous(ctx.user_id, key)
            if previous:
                if previous.request_fingerprint != digest:
                    raise AppError("resident.idempotency_conflict")
                return resident_claim_view(previous), False
            phone = self.identity.binding(ctx.user_id, data.phone_binding_id, lock=True)
            if phone.status != "active":
                raise AppError("resident.phone_unavailable")
            scope = self.repo.house(data.house_id, lock=True)
            if not self.repo.enabled(*scope):
                raise AppError("resident.housing_unavailable")
            _, community, house, path = scope
            if self.repo.active_binding(ctx.user_id, house.id):
                raise AppError("resident.already_claimed")
            if self.repo.pending_claim(ctx.user_id, house.id):
                raise AppError("resident.duplicate_claim")
            owner = self.repo.match(house.id, data.applicant_name, phone.phone)
            claim = HouseClaim(
                id=new_id(),
                user_id=ctx.user_id,
                property_company_id=company.id,
                community_id=community.id,
                house_id=house.id,
                house_label_snapshot=self.repo.label(community, house, path),
                applicant_name=data.applicant_name,
                applicant_phone=phone.phone,
                applicant_remark=data.applicant_remark,
                match_status="matched" if owner else "unmatched",
                matched_owner_id=owner.id if owner else None,
                status="pending",
                row_version=1,
                idempotency_key=key,
                request_fingerprint=digest,
            )
            self.db.add(claim)
            self.db.commit()
            return resident_claim_view(claim), True
        except IntegrityError as exc:
            self.db.rollback()
            if is_unique_violation(exc, "uq_house_claim_pending"):
                raise AppError("resident.duplicate_claim") from None
            if is_unique_violation(exc, "uq_house_claim_key"):
                raise AppError("resident.idempotency_conflict") from None
            raise
        except Exception:
            self.db.rollback()
            raise

    def get_claim(self, ctx: ClientAuthorization, claim_id: str) -> schema.ResidentHouseClaim:
        self.identity.user(ctx.user_id, ctx.version)
        return resident_claim_view(self.repo.claim(claim_id, user_id=ctx.user_id))

    def claims(self, ctx: ClientAuthorization, **filters: Any) -> schema.ResidentHouseClaimPage:
        self.identity.user(ctx.user_id, ctx.version)
        items, total = self.repo.records(HouseClaim, user_id=ctx.user_id, **filters)
        return schema.ResidentHouseClaimPage(
            items=[resident_claim_view(i) for i in items],
            total=total,
            page=filters["page"],
            page_size=filters["page_size"],
        )

    def cancel(
        self, ctx: ClientAuthorization, claim_id: str, data: schema.ClaimCancellation
    ) -> schema.ResidentHouseClaim:
        try:
            claim = self.repo.claim(claim_id, user_id=ctx.user_id)
            self.repo.company(claim.property_company_id)
            self.identity.user(ctx.user_id, ctx.version, lock=True)
            result = self.repo.transition_claim(claim, data.expected_row_version, "cancelled")
            self.db.commit()
            return resident_claim_view(result)
        except Exception:
            self.db.rollback()
            raise

    def _binding_view(self, item: ResidentHouseBinding) -> schema.ResidentHouseBinding:
        claim = self.repo.claim(item.claim_application_id, user_id=item.user_id)
        scope = self.repo.house(item.house_id)
        return resident_binding_view(
            item, claim, item.status == "active" and self.repo.enabled(*scope)
        )

    def get_binding(self, ctx: ClientAuthorization, binding_id: str) -> schema.ResidentHouseBinding:
        self.identity.user(ctx.user_id, ctx.version)
        return self._binding_view(self.repo.binding(binding_id, user_id=ctx.user_id))

    def bindings(self, ctx: ClientAuthorization, **filters: Any) -> schema.ResidentHouseBindingPage:
        self.identity.user(ctx.user_id, ctx.version)
        items, total = self.repo.records(ResidentHouseBinding, user_id=ctx.user_id, **filters)
        return schema.ResidentHouseBindingPage(
            items=[self._binding_view(i) for i in items],
            total=total,
            page=filters["page"],
            page_size=filters["page_size"],
        )

    def release(
        self, ctx: ClientAuthorization, binding_id: str, data: schema.HouseRelease
    ) -> schema.ResidentHouseBinding:
        try:
            item = self.repo.binding(binding_id, user_id=ctx.user_id)
            self.repo.company(item.property_company_id)
            self.identity.user(ctx.user_id, ctx.version, lock=True)
            result = self.repo.end_binding(
                item, data.expected_row_version, "released", user_id=ctx.user_id, reason=data.reason
            )
            self.db.commit()
            return self._binding_view(result)
        except Exception:
            self.db.rollback()
            raise

    def communities(
        self, ctx: ClientAuthorization, *, name: str | None, page: int, page_size: int
    ) -> schema.ClaimableCommunityPage:
        self.identity.user(ctx.user_id, ctx.version)
        query = (
            select(Community)
            .join(PropertyCompany)
            .where(Community.enabled.is_(True), PropertyCompany.enabled.is_(True))
        )
        if name is not None:
            query = query.where(Community.name.icontains(name.strip(), autoescape=True))
        items, total = read_page(
            self.db,
            Community,
            query,
            page=page,
            page_size=page_size,
            order=(("created_at", False), ("id", False)),
        )
        return schema.ClaimableCommunityPage(
            items=[schema.ClaimableCommunity.model_validate(i) for i in items],
            total=total,
            page=page,
            page_size=page_size,
        )

    def nodes(
        self,
        ctx: ClientAuthorization,
        community_id: str,
        *,
        parent_id: str | None,
        page: int,
        page_size: int,
    ) -> schema.ClaimableSpaceNodePage:
        self.identity.user(ctx.user_id, ctx.version)
        self.repo.claimable_community(community_id)
        active = self.repo.enabled_nodes(community_id)
        if (
            parent_id is not None
            and self.db.scalar(select(active.c.id).where(active.c.id == parent_id)) is None
        ):
            raise AppError("resource.not_found")
        child = aliased(SpaceNode)
        has_children = (
            select(child.id)
            .where(child.parent_id == SpaceNode.id, child.enabled.is_(True))
            .exists()
            .label("has_children")
        )
        query = select(SpaceNode, has_children).where(
            SpaceNode.community_id == community_id,
            SpaceNode.parent_id == parent_id,
            SpaceNode.id.in_(select(active.c.id)),
        )
        rows = self.db.execute(
            page_statement(
                SpaceNode,
                query,
                page=page,
                page_size=page_size,
                order=(("sort_order", False), ("id", False)),
                extra=("has_children",),
            )
        ).all()
        return schema.ClaimableSpaceNodePage(
            items=[
                schema.ClaimableSpaceNode(
                    id=n.id,
                    community_id=n.community_id,
                    parent_id=n.parent_id,
                    name=n.name,
                    node_type=cast(SpaceType, n.node_type),
                    has_children=children,
                )
                for n, children in [
                    (cast(SpaceNode, r[0]), bool(r[1])) for r in rows if r[0] is not None
                ]
            ],
            total=rows[0][-1],
            page=page,
            page_size=page_size,
        )

    def houses(
        self,
        ctx: ClientAuthorization,
        community_id: str,
        *,
        space_node_id: str,
        room_no: str | None,
        page: int,
        page_size: int,
    ) -> schema.ClaimableHousePage:
        self.identity.user(ctx.user_id, ctx.version)
        community = self.repo.claimable_community(community_id)
        active = self.repo.enabled_nodes(community_id)
        if self.db.scalar(select(active.c.id).where(active.c.id == space_node_id)) is None:
            raise AppError("resource.not_found")
        query = self.repo.claimable_houses(community_id).where(House.space_node_id == space_node_id)
        if room_no is not None:
            query = query.where(House.room_no.icontains(room_no.strip(), autoescape=True))
        items, total = read_page(
            self.db,
            House,
            query,
            page=page,
            page_size=page_size,
            order=(("room_no", False), ("id", False)),
        )
        paths = HousingRepository(self.db, community.property_company_id).paths(
            community.id, [i.space_node_id for i in items]
        )
        return schema.ClaimableHousePage(
            items=[
                schema.ClaimableHouse(
                    id=i.id,
                    community_id=i.community_id,
                    space_node_id=i.space_node_id,
                    room_no=i.room_no,
                    display_address=self.repo.label(community, i, paths[i.space_node_id]),
                )
                for i in items
            ],
            total=total,
            page=page,
            page_size=page_size,
        )

    def house(
        self, ctx: ClientAuthorization, community_id: str, house_id: str
    ) -> schema.ClaimableHouse:
        self.identity.user(ctx.user_id, ctx.version)
        self.repo.claimable_community(community_id)
        item = self.db.scalar(self.repo.claimable_houses(community_id).where(House.id == house_id))
        if item is None:
            raise AppError("resource.not_found")
        _, community, house, path = self.repo.house(item.id)
        return schema.ClaimableHouse(
            id=item.id,
            community_id=community_id,
            space_node_id=item.space_node_id,
            room_no=item.room_no,
            display_address=self.repo.label(community, house, path),
        )
