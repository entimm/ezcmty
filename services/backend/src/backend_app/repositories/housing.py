from collections.abc import Sequence
from typing import cast

from sqlalchemy import Select, literal, select
from sqlalchemy.orm import Session, aliased
from sqlalchemy.sql.selectable import CTE

from backend_app.models.housing import House, HouseOwner, SpaceNode
from backend_app.models.property import Community
from backend_app.repositories.pagination import page_statement, read_page


class HousingRepository:
    def __init__(self, db: Session, company_id: str):
        self.db = db
        self.company_id = company_id

    def _nodes(self, community_id: str) -> Select[SpaceNode]:
        return (
            select(SpaceNode)
            .join(Community, Community.id == SpaceNode.community_id)
            .where(Community.property_company_id == self.company_id, Community.id == community_id)
        )

    def node(self, community_id: str, node_id: str, *, lock: bool = False) -> SpaceNode | None:
        query = self._nodes(community_id).where(SpaceNode.id == node_id)
        if lock:
            query = query.with_for_update(of=SpaceNode).execution_options(populate_existing=True)
        return self.db.scalar(query)

    def community(self, community_id: str) -> Community | None:
        return self.db.scalar(
            select(Community).where(
                Community.id == community_id, Community.property_company_id == self.company_id
            )
        )

    def location_nodes(
        self, community_id: str, parent_id: str | None, node_type: str, name: str
    ) -> list[SpaceNode]:
        return list(
            self.db.scalars(
                self._nodes(community_id).where(
                    SpaceNode.parent_id == parent_id,
                    SpaceNode.node_type == node_type,
                    SpaceNode.name == name,
                )
            )
        )

    def location_houses(self, community_id: str, node_id: str, room_no: str) -> list[House]:
        return list(
            self.db.scalars(
                self._houses(community_id).where(
                    House.space_node_id == node_id, House.room_no == room_no
                )
            )
        )

    def has_children(self, community_id: str, node_id: str) -> bool:
        return bool(
            self.db.scalar(
                select(
                    select(SpaceNode.id)
                    .where(SpaceNode.community_id == community_id, SpaceNode.parent_id == node_id)
                    .exists()
                )
            )
        )

    def nodes(
        self, community_id: str, *, parent_id: str | None, page: int, page_size: int
    ) -> tuple[list[tuple[SpaceNode, bool]], int]:
        child = aliased(SpaceNode)
        has_children = (
            select(child.id)
            .where(child.community_id == SpaceNode.community_id, child.parent_id == SpaceNode.id)
            .exists()
            .label("has_children")
        )
        query = (
            self._nodes(community_id)
            .add_columns(has_children)
            .where(SpaceNode.parent_id == parent_id)
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
        return [(row[0], row[1]) for row in rows if row[0] is not None], rows[0][-1]

    def paths(self, community_id: str, node_ids: Sequence[str]) -> dict[str, list[SpaceNode]]:
        if not node_ids:
            return {}
        lineage = (
            select(
                SpaceNode.id,
                SpaceNode.parent_id,
                SpaceNode.community_id,
                SpaceNode.id.label("leaf_id"),
                literal(0).label("depth"),
            )
            .join(Community, Community.id == SpaceNode.community_id)
            .where(
                Community.property_company_id == self.company_id,
                SpaceNode.community_id == community_id,
                SpaceNode.id.in_(set(node_ids)),
            )
            .cte("space_lineage", recursive=True)
        )
        parent = aliased(SpaceNode)
        lineage = lineage.union_all(
            select(
                parent.id,
                parent.parent_id,
                parent.community_id,
                lineage.c.leaf_id,
                lineage.c.depth + 1,
            )
            .join(lineage, parent.id == lineage.c.parent_id)
            .where(parent.community_id == lineage.c.community_id, lineage.c.depth < 2)
        )
        rows = self.db.execute(
            select(SpaceNode, lineage.c.leaf_id)
            .join(lineage, SpaceNode.id == lineage.c.id)
            .order_by(lineage.c.leaf_id, lineage.c.depth.desc())
        )
        paths: dict[str, list[SpaceNode]] = {}
        for row in rows:
            paths.setdefault(cast(str, row[1]), []).append(cast(SpaceNode, row[0]))
        return paths

    def descendant_ids(self, community_id: str, node_id: str) -> CTE:
        subtree = (
            select(SpaceNode.id, literal(0).label("depth"))
            .join(Community, Community.id == SpaceNode.community_id)
            .where(
                Community.property_company_id == self.company_id,
                SpaceNode.community_id == community_id,
                SpaceNode.id == node_id,
            )
            .cte("space_subtree", recursive=True)
        )
        child = aliased(SpaceNode)
        return subtree.union_all(
            select(child.id, subtree.c.depth + 1)
            .join(subtree, child.parent_id == subtree.c.id)
            .where(child.community_id == community_id, subtree.c.depth < 2)
        )

    def _houses(self, community_id: str) -> Select[House]:
        return (
            select(House)
            .join(Community, Community.id == House.community_id)
            .where(Community.property_company_id == self.company_id, Community.id == community_id)
        )

    def house(self, community_id: str, house_id: str, *, lock: bool = False) -> House | None:
        query = self._houses(community_id).where(House.id == house_id)
        if lock:
            query = query.with_for_update(of=House).execution_options(populate_existing=True)
        return self.db.scalar(query)

    def space_path(
        self, community_id: str, node_id: str, *, lock: bool = False, exclusive: bool = False
    ) -> list[SpaceNode]:
        path = self.paths(community_id, [node_id]).get(node_id, [])
        if lock:
            refreshed = []
            for node in path:
                current = self.db.scalar(
                    self._nodes(community_id)
                    .where(SpaceNode.id == node.id)
                    .with_for_update(read=not exclusive, of=SpaceNode)
                    .execution_options(populate_existing=True)
                )
                if current is None:
                    return []
                refreshed.append(current)
            return refreshed
        return path

    def house_path(
        self, community_id: str, house_id: str, *, lock: bool = False, exclusive: bool = False
    ) -> tuple[House | None, list[SpaceNode]]:
        """Read a scoped house; callers protect company/account/community first."""
        house = self.house(community_id, house_id)
        if house is None:
            return None, []
        path = self.space_path(community_id, house.space_node_id, lock=lock)
        if lock:
            house = self.db.scalar(
                self._houses(community_id)
                .where(House.id == house_id)
                .with_for_update(read=not exclusive, of=House)
                .execution_options(populate_existing=True)
            )
        return house, path

    def houses(
        self,
        community_id: str,
        *,
        page: int,
        page_size: int,
        sort: str,
        space_node_id: str | None = None,
        room_no: str | None = None,
        external_code: str | None = None,
        floor_no: int | None = None,
        enabled: bool | None = None,
        house_id: str | None = None,
    ) -> tuple[list[House], int]:
        query = self._houses(community_id)
        if house_id is not None:
            query = query.where(House.id == house_id)
        if space_node_id is not None:
            descendants = self.descendant_ids(community_id, space_node_id)
            query = query.where(House.space_node_id.in_(select(descendants.c.id)))
        if room_no is not None:
            query = query.where(House.room_no == room_no.strip())
        if external_code is not None:
            query = query.where(House.external_code == external_code.strip())
        if floor_no is not None:
            query = query.where(House.floor_no == floor_no)
        if enabled is not None:
            query = query.where(House.enabled == enabled)
        return read_page(
            self.db,
            House,
            query,
            page=page,
            page_size=page_size,
            order=(("created_at", sort.startswith("-")), ("id", sort.startswith("-"))),
        )

    def _owners(self, community_id: str, house_id: str) -> Select[HouseOwner]:
        return (
            select(HouseOwner)
            .join(House, House.id == HouseOwner.house_id)
            .join(Community, Community.id == House.community_id)
            .where(
                Community.property_company_id == self.company_id,
                Community.id == community_id,
                House.id == house_id,
            )
        )

    def owner(
        self, community_id: str, house_id: str, owner_id: str, *, lock: bool = False
    ) -> HouseOwner | None:
        query = self._owners(community_id, house_id).where(HouseOwner.id == owner_id)
        if lock:
            query = query.with_for_update(of=HouseOwner).execution_options(populate_existing=True)
        return self.db.scalar(query)

    def owners(
        self, community_id: str, house_id: str, *, page: int, page_size: int, sort: str
    ) -> tuple[list[HouseOwner], int]:
        return read_page(
            self.db,
            HouseOwner,
            self._owners(community_id, house_id),
            page=page,
            page_size=page_size,
            order=(("created_at", sort.startswith("-")), ("id", sort.startswith("-"))),
        )

    def owner_by_contact(
        self,
        community_id: str,
        house_id: str,
        name: str,
        phone: str,
        *,
        lock: bool = False,
    ) -> HouseOwner | None:
        query = self._owners(community_id, house_id).where(
            HouseOwner.name == name, HouseOwner.phone == phone
        )
        if lock:
            query = query.with_for_update(of=HouseOwner).execution_options(populate_existing=True)
        return self.db.scalar(query)
