"""Test-only subject adapters; never registered by a production application."""

from typing import Any

from sqlalchemy import Boolean, Column, MetaData, Select, String, Table, select
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Session
from sqlalchemy.sql.selectable import Subquery

from backend_app.core.errors import AppError
from backend_app.domain.client.types import (
    ClientAuthorization,
    ExtraIdentityAuthorization,
    IdentityLink,
    IdentityResolution,
)
from backend_app.services.client.identities import ClientIdentityRegistry

SUBJECTS = Table(
    "test_client_subjects",
    MetaData(),
    Column("id", UUID(as_uuid=False), primary_key=True),
    Column("name", String(160), nullable=False),
    Column("enabled", Boolean, nullable=False),
)


class TestIdentityProvider:
    __test__ = False

    def __init__(self, db: Session, identity_type: str, *, enabled: bool = True):
        self.db = db
        self.identity_type = identity_type
        self.enabled = enabled
        self.failed = False

    def lock_parent(self, user: ClientAuthorization, link: IdentityLink) -> None:
        # These deliberately minimal subjects have no company/account ancestors.
        pass

    def resolve(
        self, user: ClientAuthorization, link: IdentityLink, *, lock: bool
    ) -> IdentityResolution | None:
        if self.failed:
            raise AppError("system.dependency_unavailable")
        query = select(SUBJECTS).where(SUBJECTS.c.id == link.subject_id)
        if lock:
            query = query.with_for_update(read=True)
        row = self.db.execute(query).one_or_none()
        if row is None or not row.enabled:
            return None
        return IdentityResolution(
            row.name,
            ExtraIdentityAuthorization(
                user.user_id,
                user.version,
                link.id,
                link.identity_type,
                link.subject_id,
                link.row_version,
            ),
        )


class TestIdentitySource:
    __test__ = False

    def __init__(self) -> None:
        self.failed = False

    def project(self, links: Subquery) -> Select[*tuple[Any, ...]]:
        if self.failed:
            raise AppError("system.dependency_unavailable")
        return (
            select(links.c.id, SUBJECTS.c.name.label("display_name"))
            .select_from(links.join(SUBJECTS, SUBJECTS.c.id == links.c.subject_id))
            .where(SUBJECTS.c.enabled.is_(True))
        )


def identity_registry(db: Session, *types: str) -> ClientIdentityRegistry:
    registry = ClientIdentityRegistry()
    for identity_type in types:
        registry.register(TestIdentityProvider(db, identity_type), TestIdentitySource())
    return registry
