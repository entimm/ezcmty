from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from backend_app.core.identifiers import new_id
from backend_app.models.imports import ImportIssue
from backend_app.repositories.pagination import read_page


def add_issue(db: Session, **values: Any) -> None:
    db.execute(
        insert(ImportIssue)
        .values(id=new_id(), **values)
        .on_conflict_do_nothing(constraint="uq_import_issue_identity")
    )


def page_issues(
    db: Session,
    batch_id: str,
    *,
    preview_version: int,
    page: int = 1,
    page_size: int = 20,
    severity: str | None = None,
    code: str | None = None,
) -> tuple[list[ImportIssue], int]:
    query = select(ImportIssue).where(
        ImportIssue.batch_id == batch_id,
        or_(ImportIssue.preview_version == 0, ImportIssue.preview_version == preview_version),
    )
    if severity is not None:
        query = query.where(ImportIssue.severity == severity)
    if code is not None:
        query = query.where(ImportIssue.code == code)
    return read_page(
        db,
        ImportIssue,
        query,
        page=page,
        page_size=page_size,
        order=(("created_at", False), ("id", False)),
    )
