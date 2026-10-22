"""Import read models; authorization is applied by the calling application service."""

from collections.abc import Iterator
from typing import Any

from sqlalchemy import Select, and_, exists, func, or_, select, true
from sqlalchemy.orm import Session

from backend_app.models.imports import (
    ImportArtifact,
    ImportBatch,
    ImportBatchEvent,
    ImportIssue,
    ImportOperation,
    ImportRow,
    ImportTask,
)


def tasks(db: Session, batch_id: str) -> list[ImportTask]:
    return list(
        db.scalars(
            select(ImportTask)
            .where(ImportTask.batch_id == batch_id)
            .order_by(ImportTask.created_at, ImportTask.id)
        )
    )


def source(db: Session, batch_id: str) -> ImportArtifact | None:
    return db.scalar(
        select(ImportArtifact).where(
            ImportArtifact.batch_id == batch_id, ImportArtifact.artifact_kind == "source"
        )
    )


def error_artifact(
    db: Session, batch_id: str, generation: int | None = None
) -> ImportArtifact | None:
    stmt = select(ImportArtifact).where(
        ImportArtifact.batch_id == batch_id, ImportArtifact.artifact_kind == "error_rows"
    )
    if generation is not None:
        stmt = stmt.where(ImportArtifact.generation == generation)
    return db.scalar(stmt.order_by(ImportArtifact.generation.desc()).limit(1))


def page(db: Session, stmt: Select[Any], page: int, page_size: int) -> tuple[list[Any], int]:
    from sqlalchemy.orm import aliased

    ordered = stmt.add_columns(
        func.row_number().over(order_by=stmt._order_by_clauses).label("page_position")
    )
    total = (
        select(func.count().label("total"))
        .select_from(stmt.order_by(None).subquery())
        .cte("import_page_total")
    )
    records = ordered.limit(page_size).offset((page - 1) * page_size).cte("import_page_records")
    entity = aliased(stmt.column_descriptions[0]["entity"], records)
    result = db.execute(
        select(entity, total.c.total)
        .select_from(total.outerjoin(records, true()))
        .order_by(records.c.page_position)
    ).all()
    return [r[0] for r in result if r[0] is not None], int(result[0][1])


def batches(
    db: Session, actor_scope: str, company_id: str | None, filters: dict[str, Any]
) -> tuple[list[ImportBatch], int]:
    stmt = select(ImportBatch).where(ImportBatch.created_by_scope == actor_scope)
    if company_id:
        stmt = stmt.where(ImportBatch.property_company_id == company_id)
    columns = {
        "import_type": "template_key",
        "scope_type": "scope_type",
        "status": "status",
        "created_by": "created_by_id",
        "property_company_id": "property_company_id",
    }
    for name, column_name in columns.items():
        if filters.get(name) is not None:
            stmt = stmt.where(getattr(ImportBatch, column_name) == filters[name])
    if filters.get("scope_id"):
        col = (
            ImportBatch.community_id
            if filters["scope_type"] == "community"
            else ImportBatch.property_company_id
        )
        stmt = stmt.where(col == filters["scope_id"])
    if filters.get("has_errors") is not None:
        stmt = stmt.where(
            (ImportBatch.error_rows + ImportBatch.failed_rows + ImportBatch.uncertain_rows > 0)
            == filters["has_errors"]
        )
    if filters.get("created_from"):
        stmt = stmt.where(ImportBatch.created_at >= filters["created_from"])
    if filters.get("created_before"):
        stmt = stmt.where(ImportBatch.created_at < filters["created_before"])
    sort = filters.get("sort") or "-created_at,-id"
    sort_column = ImportBatch.updated_at if "updated_at" in sort else ImportBatch.created_at
    stmt = stmt.order_by(
        sort_column.desc() if sort.startswith("-") else sort_column,
        ImportBatch.id.desc() if sort.startswith("-") else ImportBatch.id,
    )
    return page(db, stmt, filters.get("page") or 1, filters.get("page_size") or 20)


def visible_issue_filter(batch: ImportBatch) -> Any:
    return and_(
        ImportIssue.batch_id == batch.id,
        or_(
            and_(ImportIssue.phase == "parse", ImportIssue.preview_version == 0),
            ImportIssue.preview_version == batch.preview_version,
        ),
    )


def rows(db: Session, batch: ImportBatch, filters: dict[str, Any]) -> tuple[list[ImportRow], int]:
    stmt = select(ImportRow).where(ImportRow.batch_id == batch.id)
    for name, col in [
        ("execution_status", "execution_status"),
        ("planned_action", "planned_action"),
        ("row_no", "source_row_no"),
    ]:
        if filters.get(name) is not None:
            stmt = stmt.where(getattr(ImportRow, col) == filters[name])
    state = filters.get("precheck_status")
    if state == "pending":
        stmt = stmt.where(ImportRow.validation_status == "staged")
    if state == "error":
        stmt = stmt.where(ImportRow.validation_status == "invalid")
    if state == "warning":
        stmt = stmt.where(ImportRow.validation_status == "valid", ImportRow.warning_count > 0)
    if state == "valid":
        stmt = stmt.where(ImportRow.validation_status == "valid", ImportRow.warning_count == 0)
    if filters.get("field_key"):
        stmt = stmt.where(
            exists(
                select(ImportIssue.id).where(
                    visible_issue_filter(batch),
                    ImportIssue.row_id == ImportRow.id,
                    ImportIssue.field_key == filters["field_key"],
                )
            )
        )
    return page(
        db,
        stmt.order_by(ImportRow.source_row_no, ImportRow.id),
        filters.get("page") or 1,
        filters.get("page_size") or 20,
    )


def issues(
    db: Session, batch: ImportBatch, filters: dict[str, Any]
) -> tuple[list[ImportIssue], int]:
    stmt = (
        select(ImportIssue)
        .outerjoin(ImportRow, ImportRow.id == ImportIssue.row_id)
        .where(visible_issue_filter(batch))
    )
    for name in ("severity", "phase", "field_key", "code"):
        if filters.get(name) is not None:
            stmt = stmt.where(getattr(ImportIssue, name) == filters[name])
    if filters.get("row_no"):
        stmt = stmt.where(ImportRow.source_row_no == filters["row_no"])
    if filters.get("retryable") is not None:
        condition = and_(
            ImportIssue.phase == "apply",
            ImportIssue.code == "import.system_error",
            ImportRow.execution_status == "failed",
            exists(
                select(ImportOperation.id).where(
                    ImportOperation.id == ImportRow.operation_id, ImportOperation.status == "failed"
                )
            ),
        )
        stmt = stmt.where(condition if filters["retryable"] else ~condition)
    return page(
        db,
        stmt.order_by(ImportRow.source_row_no.nullsfirst(), ImportIssue.id),
        filters.get("page") or 1,
        filters.get("page_size") or 20,
    )


def row_issues(db: Session, batch: ImportBatch, row_ids: list[str]) -> list[ImportIssue]:
    return (
        list(
            db.scalars(
                select(ImportIssue)
                .where(visible_issue_filter(batch), ImportIssue.row_id.in_(row_ids))
                .order_by(ImportIssue.created_at, ImportIssue.id)
            )
        )
        if row_ids
        else []
    )


def events(
    db: Session, batch_id: str, filters: dict[str, Any]
) -> tuple[list[ImportBatchEvent], int]:
    return page(
        db,
        select(ImportBatchEvent)
        .where(ImportBatchEvent.batch_id == batch_id)
        .order_by(ImportBatchEvent.sequence_no),
        filters.get("page") or 1,
        filters.get("page_size") or 20,
    )


def _retryable_query(batch: ImportBatch) -> Select[ImportRow]:
    return (
        select(ImportRow)
        .join(ImportOperation, ImportOperation.id == ImportRow.operation_id)
        .where(
            ImportRow.batch_id == batch.id,
            ImportRow.execution_status == "failed",
            ImportOperation.status == "failed",
            ImportRow.raw_values.is_not(None),
            exists(
                select(ImportIssue.id).where(
                    ImportIssue.batch_id == batch.id,
                    ImportIssue.row_id == ImportRow.id,
                    ImportIssue.phase == "apply",
                    ImportIssue.code == "import.system_error",
                )
            ),
        )
    )


def retryable_count(db: Session, batch: ImportBatch) -> int:
    return int(db.scalar(select(func.count()).select_from(_retryable_query(batch).subquery())) or 0)


def iter_retryable_rows(db: Session, batch: ImportBatch) -> Iterator[ImportRow]:
    yield from db.scalars(
        _retryable_query(batch).order_by(ImportRow.source_row_no).execution_options(yield_per=200)
    )


def retryable_rows(db: Session, batch: ImportBatch) -> list[ImportRow]:
    return list(iter_retryable_rows(db, batch))


def retryable_row_ids(db: Session, batch: ImportBatch, row_ids: list[str]) -> set[str]:
    return (
        set(
            db.scalars(
                _retryable_query(batch)
                .with_only_columns(ImportRow.id)
                .where(ImportRow.id.in_(row_ids))
            )
        )
        if row_ids
        else set()
    )


def excluded_count(db: Session, batch_id: str) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(ImportRow)
            .where(ImportRow.batch_id == batch_id, ImportRow.execution_status == "excluded")
        )
        or 0
    )


def rows_by_ids(db: Session, ids: list[str]) -> dict[str, ImportRow]:
    return (
        {row.id: row for row in db.scalars(select(ImportRow).where(ImportRow.id.in_(ids)))}
        if ids
        else {}
    )


def has_blocking_issue(db: Session, batch: ImportBatch) -> bool:
    return bool(
        db.scalar(
            select(
                exists(
                    select(ImportIssue.id).where(
                        visible_issue_filter(batch),
                        ImportIssue.severity == "error",
                        or_(
                            ImportIssue.row_id.is_(None),
                            ImportIssue.code.in_(
                                [
                                    "import.scope_mismatch",
                                    "import.template_unavailable",
                                    "import.template_drift",
                                    "import.file_invalid",
                                    "auth.forbidden",
                                    "auth.unauthenticated",
                                ]
                            ),
                        ),
                    )
                )
            )
        )
    )


def selected_count(db: Session, batch: ImportBatch, include_warning_rows: bool) -> int:
    stmt = (
        select(func.count())
        .select_from(ImportRow)
        .where(
            ImportRow.batch_id == batch.id,
            ImportRow.validation_status == "valid",
            ImportRow.operation_id.is_not(None),
            ImportRow.planned_action.in_(["create", "skip"]),
        )
    )
    if not include_warning_rows:
        stmt = stmt.where(ImportRow.warning_count == 0)
    return int(db.scalar(stmt) or 0)


def has_export_rows(db: Session, batch: ImportBatch) -> bool:
    return bool(
        db.scalar(
            select(
                exists(
                    select(ImportRow.id).where(
                        ImportRow.batch_id == batch.id,
                        or_(
                            ImportRow.error_count > 0,
                            ImportRow.warning_count > 0,
                            ImportRow.execution_status.in_(["failed", "uncertain"]),
                        ),
                    )
                )
            )
        )
    )
