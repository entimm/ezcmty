from sqlalchemy import select, update
from sqlalchemy.orm import Session

from backend_app.core.identifiers import normalize_property_code
from backend_app.models.admin import AdminAccount
from backend_app.models.property import Community, PropertyCompany
from backend_app.repositories.pagination import page_statement, read_page


class PropertyRepository:
    def __init__(self, db: Session):
        self.db = db

    def company(self, company_id: str, *, lock: bool = False) -> PropertyCompany | None:
        query = select(PropertyCompany).where(PropertyCompany.id == company_id)
        if lock:
            query = query.with_for_update(of=PropertyCompany).execution_options(
                populate_existing=True
            )
        return self.db.scalar(query)

    def company_by_code(self, code: str) -> PropertyCompany | None:
        return self.db.scalar(
            select(PropertyCompany).where(PropertyCompany.code == normalize_property_code(code))
        )

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
        if name:
            query = query.where(PropertyCompany.name.icontains(name, autoescape=True))
        if code:
            query = query.where(
                PropertyCompany.code.contains(normalize_property_code(code), autoescape=True)
            )
        if enabled is not None:
            query = query.where(PropertyCompany.enabled == enabled)
        return read_page(
            self.db,
            PropertyCompany,
            query,
            page=page,
            page_size=page_size,
            order=(("created_at", sort.startswith("-")), ("id", False)),
        )

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
            query = query.with_for_update(of=Community).execution_options(populate_existing=True)
        return self.db.scalar(query)

    def community_by_code(self, code: str) -> Community | None:
        return self.db.scalar(
            select(Community).where(Community.code == normalize_property_code(code))
        )

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
        query = select(Community, PropertyCompany.name.label("company_name")).join(
            PropertyCompany, Community.property_company_id == PropertyCompany.id
        )
        if name:
            query = query.where(Community.name.icontains(name, autoescape=True))
        if code:
            query = query.where(
                Community.code.contains(normalize_property_code(code), autoescape=True)
            )
        if property_company_id is not None:
            query = query.where(Community.property_company_id == property_company_id)
        if company_scope_id is not None:
            query = query.where(Community.property_company_id == company_scope_id)
        if enabled is not None:
            query = query.where(Community.enabled == enabled)
        rows = self.db.execute(
            page_statement(
                Community,
                query,
                page=page,
                page_size=page_size,
                order=(("created_at", sort.startswith("-")), ("id", False)),
                extra=("company_name",),
            )
        ).all()
        return [(row[0], row[1]) for row in rows if row[0] is not None], rows[0][-1]

    def invalidate_company_accounts(self, company_id: str) -> None:
        self.db.execute(
            update(AdminAccount)
            .where(
                AdminAccount.scope == "property_admin",
                AdminAccount.property_company_id == company_id,
            )
            .values(session_version=AdminAccount.session_version + 1)
        )
