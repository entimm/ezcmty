from datetime import datetime
from typing import Any, Protocol

from sqlalchemy import Select, String, cast, func, literal, select, true, union_all, update
from sqlalchemy.orm import Session
from sqlalchemy.sql.selectable import Subquery

from backend_app.core.errors import AppError
from backend_app.domain.client.types import ClientIdentityDescriptor, IdentityLink
from backend_app.models.admin import utc_now
from backend_app.models.miniapp import MiniappUser, MiniappUserIdentity


class IdentityDirectorySource(Protocol):
    def project(self, links: Subquery) -> Select[*tuple[Any, ...]]:
        """Return one id/display_name row per eligible link, before directory pagination.

        The supplied links already restrict owner, registered type and active status.
        Subject validity and the allowed public name must be expressed in SQL here.
        """
        ...


class ClientIdentityRepository:
    def __init__(self, db: Session):
        self.db = db

    def owned(self, user_id: str, identity_id: str, *, lock: bool = False) -> MiniappUserIdentity:
        query = select(MiniappUserIdentity).where(
            MiniappUserIdentity.id == identity_id, MiniappUserIdentity.user_id == user_id
        )
        if lock:
            query = query.with_for_update(read=True, of=MiniappUserIdentity)
        item = self.db.scalar(query.execution_options(populate_existing=True))
        if item is None:
            raise AppError("resource.not_found")
        return item

    @staticmethod
    def snapshot(item: MiniappUserIdentity) -> IdentityLink:
        return IdentityLink(
            item.id, item.user_id, item.identity_type, item.subject_id, item.row_version
        )

    def list(
        self,
        user_id: str,
        sources: dict[str, IdentityDirectorySource],
        *,
        page: int,
        page_size: int,
    ) -> tuple[list[ClientIdentityDescriptor], int]:
        if page < 1 or not 1 <= page_size <= 100:
            raise ValueError("Invalid identity pagination")
        resident = select(
            literal("resident").label("id"),
            literal("resident").label("type"),
            literal("居民").label("display_name"),
            literal(0).label("rank"),
            MiniappUser.created_at.label("created_at"),
        ).where(MiniappUser.id == user_id)
        queries: list[Select[*tuple[Any, ...]]] = [resident]
        for identity_type, source in sources.items():
            links = (
                select(MiniappUserIdentity)
                .where(
                    MiniappUserIdentity.user_id == user_id,
                    MiniappUserIdentity.identity_type == identity_type,
                    MiniappUserIdentity.status == "active",
                )
                .subquery()
            )
            projection = source.project(links).subquery()
            queries.append(
                select(
                    cast(links.c.id, String).label("id"),
                    links.c.identity_type.label("type"),
                    projection.c.display_name.label("display_name"),
                    literal(1).label("rank"),
                    links.c.created_at.label("created_at"),
                ).select_from(links.join(projection, projection.c.id == links.c.id))
            )
        candidates = union_all(*queries).cte("identity_candidates")
        total = select(func.count().label("total")).select_from(candidates).cte("identity_total")
        records = (
            select(candidates)
            .order_by(candidates.c.rank, candidates.c.created_at, candidates.c.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
            .cte("identity_records")
        )
        rows = self.db.execute(
            select(records.c.id, records.c.type, records.c.display_name, total.c.total)
            .select_from(total.outerjoin(records, true()))
            .order_by(records.c.rank, records.c.created_at, records.c.id)
        ).all()
        return (
            [
                ClientIdentityDescriptor(row.id, row.type, row.display_name)
                for row in rows
                if row.id
            ],
            rows[0].total,
        )

    def revoke(self, user_id: str, identity_id: str, expected_version: int) -> None:
        now: datetime = utc_now()
        changed = self.db.scalar(
            update(MiniappUserIdentity)
            .where(
                MiniappUserIdentity.id == identity_id,
                MiniappUserIdentity.user_id == user_id,
                MiniappUserIdentity.status == "active",
                MiniappUserIdentity.row_version == expected_version,
            )
            .values(
                status="revoked",
                revoked_at=now,
                updated_at=now,
                row_version=MiniappUserIdentity.row_version + 1,
            )
            .returning(MiniappUserIdentity.id)
            .execution_options(synchronize_session=False)
        )
        if changed is None:
            item = self.owned(user_id, identity_id)
            if item.status != "active":
                raise AppError("client.identity_unavailable")
            raise AppError("resource.conflict")
