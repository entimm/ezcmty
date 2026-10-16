from datetime import datetime
from typing import Any

from sqlalchemy import Select, literal, select, update
from sqlalchemy.orm import Session, aliased
from sqlalchemy.sql.selectable import CTE

from backend_app.core.errors import AppError
from backend_app.models.admin import AdminAccount, utc_now
from backend_app.models.house_claims import HouseClaim, ResidentHouseBinding
from backend_app.models.housing import House, HouseOwner, SpaceNode
from backend_app.models.miniapp import MiniappUser
from backend_app.models.property import Community, PropertyCompany
from backend_app.repositories.housing import HousingRepository
from backend_app.repositories.pagination import read_page


class HouseClaimRepository:
    def __init__(self, db: Session):
        self.db = db

    def claim(
        self, claim_id: str, *, user_id: str | None = None, company_id: str | None = None
    ) -> HouseClaim:
        query = select(HouseClaim).where(HouseClaim.id == claim_id)
        if user_id is not None:
            query = query.where(HouseClaim.user_id == user_id)
        if company_id is not None:
            query = query.where(HouseClaim.property_company_id == company_id)
        item = self.db.scalar(query.execution_options(populate_existing=True))
        if item is None:
            raise AppError("resource.not_found")
        return item

    def binding(
        self, binding_id: str, *, user_id: str | None = None, company_id: str | None = None
    ) -> ResidentHouseBinding:
        query = select(ResidentHouseBinding).where(ResidentHouseBinding.id == binding_id)
        if user_id is not None:
            query = query.where(ResidentHouseBinding.user_id == user_id)
        if company_id is not None:
            query = query.where(ResidentHouseBinding.property_company_id == company_id)
        item = self.db.scalar(query.execution_options(populate_existing=True))
        if item is None:
            raise AppError("resource.not_found")
        return item

    def previous(self, user_id: str, key: str) -> HouseClaim | None:
        return self.db.scalar(
            select(HouseClaim).where(
                HouseClaim.user_id == user_id, HouseClaim.idempotency_key == key
            )
        )

    def user(
        self, user_id: str, *, require_enabled: bool = False, exclusive: bool = False
    ) -> MiniappUser:
        user = self.db.scalar(
            select(MiniappUser)
            .where(MiniappUser.id == user_id)
            .with_for_update(read=not exclusive, of=MiniappUser)
            .execution_options(populate_existing=True)
        )
        if user is None or (require_enabled and not user.enabled):
            raise AppError("resident.housing_unavailable")
        return user

    def company(self, company_id: str) -> PropertyCompany:
        item = self.db.scalar(
            select(PropertyCompany)
            .where(PropertyCompany.id == company_id)
            .with_for_update(read=True, of=PropertyCompany)
            .execution_options(populate_existing=True)
        )
        if item is None:
            raise AppError("resource.not_found")
        return item

    def actor(self, company_id: str, actor_id: str) -> AdminAccount:
        actor = self.db.scalar(
            select(AdminAccount)
            .where(
                AdminAccount.id == actor_id,
                AdminAccount.property_company_id == company_id,
                AdminAccount.scope == "property_admin",
            )
            .with_for_update(read=True, of=AdminAccount)
            .execution_options(populate_existing=True)
        )
        if actor is None:
            raise AppError("auth.unauthenticated")
        return actor

    def house(
        self, house_id: str, *, lock: bool = False
    ) -> tuple[PropertyCompany, Community, House, list[SpaceNode]]:
        row = self.db.execute(
            select(PropertyCompany, Community, House)
            .join(Community, Community.property_company_id == PropertyCompany.id)
            .join(House, House.community_id == Community.id)
            .where(House.id == house_id)
        ).first()
        if row is None:
            raise AppError("resource.not_found")
        company, community, house = row
        paths = HousingRepository(self.db, company.id).paths(community.id, [house.space_node_id])
        path = paths.get(house.space_node_id, [])
        if lock:
            community = self.db.scalars(
                select(Community)
                .where(Community.id == community.id)
                .with_for_update(read=True, of=Community)
                .execution_options(populate_existing=True)
            ).one()
            for node in path:
                self.db.execute(
                    select(SpaceNode)
                    .where(SpaceNode.id == node.id)
                    .with_for_update(read=True, of=SpaceNode)
                    .execution_options(populate_existing=True)
                ).scalar_one()
            house = self.db.scalars(
                select(House)
                .where(House.id == house_id)
                .with_for_update(read=True, of=House)
                .execution_options(populate_existing=True)
            ).one()
        return company, community, house, path

    @staticmethod
    def enabled(
        company: PropertyCompany, community: Community, house: House, path: list[SpaceNode]
    ) -> bool:
        return (
            company.enabled
            and community.enabled
            and house.enabled
            and bool(path)
            and all(n.enabled for n in path)
        )

    @staticmethod
    def label(community: Community, house: House, path: list[SpaceNode]) -> str:
        return "／".join([community.name, *(node.name for node in path), house.room_no])

    def match(self, house_id: str, name: str, phone: str) -> HouseOwner | None:
        return self.db.scalar(
            select(HouseOwner)
            .where(
                HouseOwner.house_id == house_id,
                HouseOwner.name == name,
                HouseOwner.phone == phone,
                HouseOwner.enabled.is_(True),
            )
            .with_for_update(read=True, of=HouseOwner)
            .execution_options(populate_existing=True)
        )

    def active_binding(self, user_id: str, house_id: str) -> ResidentHouseBinding | None:
        return self.db.scalar(
            select(ResidentHouseBinding).where(
                ResidentHouseBinding.user_id == user_id,
                ResidentHouseBinding.house_id == house_id,
                ResidentHouseBinding.status == "active",
            )
        )

    def pending_claim(self, user_id: str, house_id: str) -> HouseClaim | None:
        return self.db.scalar(
            select(HouseClaim).where(
                HouseClaim.user_id == user_id,
                HouseClaim.house_id == house_id,
                HouseClaim.status == "pending",
            )
        )

    def transition_claim(
        self,
        claim: HouseClaim,
        version: int,
        status: str,
        *,
        actor_id: str | None = None,
        reason: str | None = None,
    ) -> HouseClaim:
        now = utc_now()
        values: dict[str, Any] = {
            "status": status,
            "row_version": HouseClaim.row_version + 1,
            "updated_at": now,
        }
        if status == "cancelled":
            values["cancelled_at"] = now
        else:
            values.update(reviewed_by_admin_id=actor_id, reviewed_at=now, review_reason=reason)
        result = self.db.scalar(
            update(HouseClaim)
            .where(
                HouseClaim.id == claim.id,
                HouseClaim.status == "pending",
                HouseClaim.row_version == version,
            )
            .values(**values)
            .returning(HouseClaim)
            .execution_options(synchronize_session=False, populate_existing=True)
        )
        if result is None:
            raise AppError("resident.state_changed")
        return result

    def end_binding(
        self,
        binding: ResidentHouseBinding,
        version: int,
        status: str,
        *,
        user_id: str | None = None,
        actor_id: str | None = None,
        reason: str | None = None,
    ) -> ResidentHouseBinding:
        now = utc_now()
        result = self.db.scalar(
            update(ResidentHouseBinding)
            .where(
                ResidentHouseBinding.id == binding.id,
                ResidentHouseBinding.status == "active",
                ResidentHouseBinding.row_version == version,
            )
            .values(
                status=status,
                row_version=ResidentHouseBinding.row_version + 1,
                updated_at=now,
                ended_at=now,
                ended_by_user_id=user_id,
                ended_by_admin_id=actor_id,
                end_reason=reason,
            )
            .returning(ResidentHouseBinding)
            .execution_options(synchronize_session=False, populate_existing=True)
        )
        if result is None:
            raise AppError("resident.state_changed")
        return result

    def records[T: (HouseClaim, ResidentHouseBinding)](
        self,
        model: type[T],
        *,
        user_id: str | None = None,
        company_id: str | None = None,
        community_id: str | None = None,
        house_id: str | None = None,
        status: str | None = None,
        match_status: str | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        page: int = 1,
        page_size: int = 20,
        sort: str = "-created_at",
    ) -> tuple[list[T], int]:
        query = select(model)
        for key, value in (
            ("user_id", user_id),
            ("property_company_id", company_id),
            ("community_id", community_id),
            ("house_id", house_id),
            ("status", status),
            ("match_status", match_status),
        ):
            if value is not None:
                query = query.where(getattr(model, key) == value)
        if created_from is not None:
            query = query.where(model.created_at >= created_from)
        if created_to is not None:
            query = query.where(model.created_at < created_to)
        return read_page(
            self.db,
            model,
            query,
            page=page,
            page_size=page_size,
            order=(("created_at", sort.startswith("-")), ("id", sort.startswith("-"))),
        )

    def enabled_nodes(self, community_id: str) -> CTE:
        nodes = (
            select(SpaceNode.id, literal(0).label("depth"))
            .where(
                SpaceNode.community_id == community_id,
                SpaceNode.parent_id.is_(None),
                SpaceNode.enabled.is_(True),
            )
            .cte("claimable_nodes", recursive=True)
        )
        child = aliased(SpaceNode)
        return nodes.union_all(
            select(child.id, (nodes.c.depth + 1).label("depth"))
            .join(nodes, child.parent_id == nodes.c.id)
            .where(child.community_id == community_id, child.enabled.is_(True), nodes.c.depth < 2)
        )

    def claimable_community(self, community_id: str) -> Community:
        item = self.db.scalar(
            select(Community)
            .join(PropertyCompany)
            .where(
                Community.id == community_id,
                Community.enabled.is_(True),
                PropertyCompany.enabled.is_(True),
            )
        )
        if item is None:
            raise AppError("resource.not_found")
        return item

    def claimable_houses(self, community_id: str) -> Select[House]:
        return select(House).where(
            House.community_id == community_id,
            House.enabled.is_(True),
            House.space_node_id.in_(select(self.enabled_nodes(community_id).c.id)),
        )
