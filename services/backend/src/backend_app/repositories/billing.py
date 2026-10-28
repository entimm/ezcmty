from collections.abc import Sequence
from datetime import date
from typing import Any

from sqlalchemy import Select, func, select, true
from sqlalchemy.orm import Session, aliased

from backend_app.models.admin import AdminAccount
from backend_app.models.billing import Bill, BillOperation, BillSettlementEntry, FeeBasisVersion
from backend_app.models.housing import House, SpaceNode
from backend_app.models.payments import BillPaymentReservation
from backend_app.models.property import Community, PropertyCompany
from backend_app.repositories.housing import HousingRepository
from backend_app.repositories.pagination import read_page


class BillingRepository:
    def __init__(self, db: Session, company_id: str):
        self.db = db
        self.company_id = company_id
        self.housing = HousingRepository(db, company_id)

    def protect_company(self) -> PropertyCompany | None:
        """Protect historical posting without requiring an administrator or enabled state."""
        return self.db.scalar(
            select(PropertyCompany)
            .where(PropertyCompany.id == self.company_id)
            .with_for_update(read=True, of=PropertyCompany)
            .execution_options(populate_existing=True)
        )

    def reservation(self, bill_id: str) -> BillPaymentReservation | None:
        return self.db.get(BillPaymentReservation, bill_id, populate_existing=True)

    def reserved_bill_ids(self, ids: Sequence[str]) -> set[str]:
        if not ids:
            return set()
        return set(
            self.db.scalars(
                select(BillPaymentReservation.bill_id).where(
                    BillPaymentReservation.bill_id.in_(ids)
                )
            )
        )

    def add_receipt(self, operation: BillOperation, entry: BillSettlementEntry) -> None:
        self.db.add(operation)
        self.db.flush()
        self.db.add(entry)

    def protect_bill_resources(self, bill_ids: Sequence[str]) -> list[Bill]:
        """Lock ancestors before bills; the caller already holds the company/user guards."""
        items = list(
            self.db.scalars(
                select(Bill).where(
                    Bill.property_company_id == self.company_id, Bill.id.in_(bill_ids)
                )
            )
        )
        if not items:
            return []
        for community_id in sorted({item.community_id for item in items}):
            self.community(community_id, lock=True)
        houses = list(
            self.db.scalars(select(House).where(House.id.in_({item.house_id for item in items})))
        )
        nodes: dict[str, SpaceNode] = {}
        for community_id in sorted({item.community_id for item in items}):
            paths = self.housing.paths(
                community_id,
                [house.space_node_id for house in houses if house.community_id == community_id],
            )
            for path in paths.values():
                nodes.update({node.id: node for node in path})
        # Shared guards coordinate ancestor changes while independent bills may post concurrently.
        for node_id in sorted(nodes):
            self.db.scalar(
                select(SpaceNode)
                .where(SpaceNode.id == node_id)
                .with_for_update(read=True, of=SpaceNode)
                .execution_options(populate_existing=True)
            )
        for house_id in sorted({house.id for house in houses}):
            self.db.scalar(
                select(House)
                .where(House.id == house_id)
                .with_for_update(read=True, of=House)
                .execution_options(populate_existing=True)
            )
        return list(
            self.db.scalars(
                select(Bill)
                .where(Bill.property_company_id == self.company_id, Bill.id.in_(bill_ids))
                .order_by(Bill.id)
                .with_for_update(of=Bill)
                .execution_options(populate_existing=True)
            )
        )

    def protect(
        self, account_id: str, community_id: str | None = None
    ) -> tuple[PropertyCompany | None, AdminAccount | None, Community | None]:
        company = self.db.scalar(
            select(PropertyCompany)
            .where(PropertyCompany.id == self.company_id)
            .with_for_update(read=True, of=PropertyCompany)
            .execution_options(populate_existing=True)
        )
        actor = self.db.scalar(
            select(AdminAccount)
            .where(
                AdminAccount.id == account_id,
                AdminAccount.property_company_id == self.company_id,
                AdminAccount.scope == "property_admin",
            )
            .with_for_update(read=True, of=AdminAccount)
            .execution_options(populate_existing=True)
        )
        community = self.community(community_id, lock=True) if community_id else None
        return company, actor, community

    def community(self, community_id: str, *, lock: bool = False) -> Community | None:
        query = select(Community).where(
            Community.id == community_id, Community.property_company_id == self.company_id
        )
        if lock:
            query = query.with_for_update(read=True, of=Community).execution_options(
                populate_existing=True
            )
        return self.db.scalar(query)

    def house(
        self, community_id: str, house_id: str, *, lock: bool = False, exclusive: bool = False
    ) -> tuple[House | None, list[SpaceNode]]:
        return self.housing.house_path(community_id, house_id, lock=lock, exclusive=exclusive)

    def basis(self, house_id: str, basis_id: str) -> FeeBasisVersion | None:
        return self.db.scalar(
            select(FeeBasisVersion).where(
                FeeBasisVersion.id == basis_id, FeeBasisVersion.house_id == house_id
            )
        )

    def effective_basis(self, house_id: str, month: date) -> FeeBasisVersion | None:
        return self.db.scalar(
            select(FeeBasisVersion)
            .where(
                FeeBasisVersion.house_id == house_id, FeeBasisVersion.effective_from_month <= month
            )
            .order_by(
                FeeBasisVersion.effective_from_month.desc(), FeeBasisVersion.version_no.desc()
            )
            .limit(1)
        )

    def latest_basis_number(self, house_id: str) -> int:
        return (
            self.db.scalar(
                select(func.coalesce(func.max(FeeBasisVersion.version_no), 0)).where(
                    FeeBasisVersion.house_id == house_id
                )
            )
            or 0
        )

    def latest_basis_for_month(self, house_id: str, month: date) -> FeeBasisVersion | None:
        return self.db.scalar(
            select(FeeBasisVersion)
            .where(
                FeeBasisVersion.house_id == house_id, FeeBasisVersion.effective_from_month == month
            )
            .order_by(FeeBasisVersion.version_no.desc())
            .limit(1)
        )

    def next_basis_month(self, house_id: str, month: date) -> date | None:
        return self.db.scalar(
            select(func.min(FeeBasisVersion.effective_from_month)).where(
                FeeBasisVersion.house_id == house_id, FeeBasisVersion.effective_from_month > month
            )
        )

    def bases(
        self, house_id: str, *, page: int, page_size: int
    ) -> tuple[list[FeeBasisVersion], int]:
        return read_page(
            self.db,
            FeeBasisVersion,
            select(FeeBasisVersion).where(FeeBasisVersion.house_id == house_id),
            page=page,
            page_size=page_size,
            order=(("version_no", True),),
        )

    def bills_query(self, community_id: str) -> Select[Bill]:
        return select(Bill).where(
            Bill.property_company_id == self.company_id, Bill.community_id == community_id
        )

    def bill(self, community_id: str, bill_id: str, *, lock: bool = False) -> Bill | None:
        query = self.bills_query(community_id).where(Bill.id == bill_id)
        if lock:
            query = query.with_for_update(of=Bill).execution_options(populate_existing=True)
        return self.db.scalar(query)

    def operation_by_key(self, key: str) -> BillOperation | None:
        return self.db.scalar(
            select(BillOperation).where(
                BillOperation.property_company_id == self.company_id,
                BillOperation.idempotency_key == key,
            )
        )

    def active_month_bill(self, community_id: str, house_id: str, month: date) -> Bill | None:
        return self.db.scalar(
            self.bills_query(community_id).where(
                Bill.house_id == house_id,
                Bill.bill_type == "property_fee",
                Bill.period_start == month,
                Bill.lifecycle_status == "active",
            )
        )

    def creation_operation(self, bill_id: str) -> BillOperation | None:
        return self.db.scalar(
            select(BillOperation).where(
                BillOperation.property_company_id == self.company_id,
                BillOperation.bill_id == bill_id,
                BillOperation.action == "create",
                BillOperation.bill_version == 1,
            )
        )

    def bill_list(
        self,
        community_id: str,
        *,
        today: date,
        page: int,
        page_size: int,
        sort: str,
        **filters: Any,
    ) -> tuple[list[Bill], int]:
        query = self.bills_query(community_id).where(
            Bill.lifecycle_status == filters["lifecycle_status"]
        )
        for field in ("house_id", "settlement_status", "external_bill_no"):
            if filters.get(field) is not None:
                query = query.where(getattr(Bill, field) == filters[field])
        if filters.get("space_node_id"):
            descendants = self.housing.descendant_ids(community_id, filters["space_node_id"])
            query = query.join(House, House.id == Bill.house_id).where(
                House.space_node_id.in_(select(descendants.c.id))
            )
        for key, column, greater in [
            ("billing_month_from", Bill.period_start, True),
            ("billing_month_to", Bill.period_start, False),
            ("due_date_from", Bill.due_date, True),
            ("due_date_to", Bill.due_date, False),
        ]:
            if filters.get(key) is not None:
                value = filters[key]
                if key.startswith("billing_month"):
                    value = date.fromisoformat(value + "-01")
                query = query.where(column >= value if greater else column <= value)
        if filters.get("outstanding_only"):
            query = query.where(Bill.outstanding_cents > 0)
        overdue = (
            (Bill.lifecycle_status == "active")
            & (Bill.outstanding_cents > 0)
            & Bill.due_date.is_not(None)
            & (Bill.due_date < today)
        )
        if filters.get("is_overdue") is not None:
            query = query.where(overdue if filters["is_overdue"] else ~overdue)
        # One statement supplies an exact count even when the requested page is empty.
        field = sort.removeprefix("-")
        descending = sort.startswith("-")
        total = select(func.count().label("total")).select_from(query.subquery()).cte("bill_total")
        column = getattr(Bill, field)
        order = (column.desc() if descending else column.asc()).nulls_last()
        records = (
            query.order_by(order, Bill.id.desc() if descending else Bill.id.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .cte("bill_records")
        )
        item = aliased(Bill, records)
        col = records.c[field]
        result = self.db.execute(
            select(item, total.c.total)
            .select_from(total.outerjoin(records, true()))
            .order_by(
                (col.desc() if descending else col.asc()).nulls_last(),
                records.c.id.desc() if descending else records.c.id.asc(),
            )
        ).all()
        return [row[0] for row in result if row[0] is not None], result[0][-1]

    def basis_map(self, ids: Sequence[str]) -> dict[str, FeeBasisVersion]:
        return (
            {
                row.id: row
                for row in self.db.scalars(
                    select(FeeBasisVersion).where(FeeBasisVersion.id.in_(ids))
                )
            }
            if ids
            else {}
        )

    def house_states(self, community: Community, house_ids: Sequence[str]) -> dict[str, bool]:
        houses = list(
            self.db.scalars(
                select(House).where(House.community_id == community.id, House.id.in_(house_ids))
            )
        )
        paths = self.housing.paths(community.id, [h.space_node_id for h in houses])
        return {
            h.id: community.enabled
            and h.enabled
            and bool(paths.get(h.space_node_id))
            and all(n.enabled for n in paths[h.space_node_id])
            for h in houses
        }

    def entry(self, bill_id: str, entry_id: str) -> BillSettlementEntry | None:
        return self.db.scalar(
            select(BillSettlementEntry).where(
                BillSettlementEntry.bill_id == bill_id, BillSettlementEntry.id == entry_id
            )
        )

    def reversals(self, ids: Sequence[str]) -> dict[str, str]:
        if not ids:
            return {}
        return {
            row.reverses_entry_id: row.id
            for row in self.db.scalars(
                select(BillSettlementEntry).where(BillSettlementEntry.reverses_entry_id.in_(ids))
            )
            if row.reverses_entry_id is not None
        }

    def entries(
        self, bill_id: str, *, page: int, page_size: int
    ) -> tuple[list[BillSettlementEntry], int]:
        return read_page(
            self.db,
            BillSettlementEntry,
            select(BillSettlementEntry).where(BillSettlementEntry.bill_id == bill_id),
            page=page,
            page_size=page_size,
            order=(("created_at", True), ("id", True)),
        )

    def operations(
        self, bill_id: str, *, page: int, page_size: int
    ) -> tuple[list[BillOperation], int]:
        return read_page(
            self.db,
            BillOperation,
            select(BillOperation).where(BillOperation.bill_id == bill_id),
            page=page,
            page_size=page_size,
            order=(("bill_version", True),),
        )

    def operation_map(self, ids: Sequence[str]) -> dict[str, BillOperation]:
        return {
            row.id: row
            for row in self.db.scalars(
                select(BillOperation).where(
                    BillOperation.id.in_(ids), BillOperation.property_company_id == self.company_id
                )
            )
        }

    def actor_names(self, ids: Sequence[str]) -> dict[str, str]:
        return {
            row.id: row.display_name
            for row in self.db.scalars(
                select(AdminAccount).where(
                    AdminAccount.id.in_(ids), AdminAccount.property_company_id == self.company_id
                )
            )
        }
