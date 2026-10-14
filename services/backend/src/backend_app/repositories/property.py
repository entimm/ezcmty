from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from backend_app.models.admin import AdminAccount
from backend_app.models.property import Community, PropertyCompany


class PropertyRepository:
    def __init__(self, db: Session):
        self.db = db

    def company(self, company_id: str, *, lock: bool = False) -> PropertyCompany | None:
        query = select(PropertyCompany).where(PropertyCompany.id == company_id)
        if lock:
            query = query.with_for_update().execution_options(populate_existing=True)
        return self.db.scalar(query)

    def company_by_code(self, code: str) -> PropertyCompany | None:
        return self.db.scalar(select(PropertyCompany).where(PropertyCompany.code == code))

    def companies(
        self,
        *,
        page: int,
        page_size: int,
        name: str | None,
        code: str | None,
        enabled: bool | None,
        sort: str,
    ) -> tuple[list[PropertyCompany], int]:
        query = select(PropertyCompany)
        for column, value in ((PropertyCompany.name, name), (PropertyCompany.code, code)):
            if value:
                query = query.where(column.contains(value, autoescape=True))
        if enabled is not None:
            query = query.where(PropertyCompany.enabled == enabled)
        total = self.db.scalar(select(func.count()).select_from(query.subquery())) or 0
        query = query.order_by(
            PropertyCompany.created_at.desc()
            if sort.startswith("-")
            else PropertyCompany.created_at,
            PropertyCompany.id,
        )
        return list(self.db.scalars(query.offset((page - 1) * page_size).limit(page_size))), total

    def community(
        self,
        community_id: str,
        *,
        lock: bool = False,
        company_scope_id: str | None = None,
    ) -> Community | None:
        query = select(Community).where(Community.id == community_id)
        if company_scope_id is not None:
            query = query.where(Community.property_company_id == company_scope_id)
        if lock:
            query = query.with_for_update().execution_options(populate_existing=True)
        return self.db.scalar(query)

    def community_by_code(self, code: str) -> Community | None:
        return self.db.scalar(select(Community).where(Community.code == code))

    def communities(
        self,
        *,
        page: int,
        page_size: int,
        name: str | None,
        code: str | None,
        property_company_id: str | None,
        enabled: bool | None,
        sort: str,
        company_scope_id: str | None = None,
    ) -> tuple[list[tuple[Community, str]], int]:
        query = select(Community, PropertyCompany.name).join(
            PropertyCompany, Community.property_company_id == PropertyCompany.id
        )
        for column, value in ((Community.name, name), (Community.code, code)):
            if value:
                query = query.where(column.contains(value, autoescape=True))
        if property_company_id is not None:
            query = query.where(Community.property_company_id == property_company_id)
        if company_scope_id is not None:
            query = query.where(Community.property_company_id == company_scope_id)
        if enabled is not None:
            query = query.where(Community.enabled == enabled)
        total = self.db.scalar(select(func.count()).select_from(query.subquery())) or 0
        query = query.order_by(
            Community.created_at.desc() if sort.startswith("-") else Community.created_at,
            Community.id,
        )
        rows = self.db.execute(query.offset((page - 1) * page_size).limit(page_size))
        return [(row[0], row[1]) for row in rows], total

    def invalidate_company_accounts(self, company_id: str) -> None:
        self.db.execute(
            update(AdminAccount)
            .where(
                AdminAccount.scope == "property_admin",
                AdminAccount.property_company_id == company_id,
            )
            .values(session_version=AdminAccount.session_version + 1)
        )
