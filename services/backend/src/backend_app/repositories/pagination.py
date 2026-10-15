from typing import Any

from sqlalchemy import Select, func, select, true
from sqlalchemy.orm import Session, aliased

from backend_app.db.base import Base


def page_statement[T: Base](
    model: type[T],
    query: Select[*tuple[Any, ...]],
    *,
    page: int,
    page_size: int,
    order: tuple[tuple[str, bool], ...],
    extra: tuple[str, ...] = (),
) -> Select[*tuple[Any, ...]]:
    """Read a page and its count from one statement snapshot, including empty pages."""
    total = select(func.count().label("total")).select_from(query.subquery()).cte("page_total")
    records = (
        query.order_by(
            *(
                getattr(model, name).desc() if descending else getattr(model, name)
                for name, descending in order
            )
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
        .cte("page_records")
    )
    item = aliased(model, records)
    return (
        select(item, *(records.c[name] for name in extra), total.c.total)
        .select_from(total.outerjoin(records, true()))
        .order_by(
            *(
                records.c[name].desc() if descending else records.c[name]
                for name, descending in order
            )
        )
    )


def read_page[T: Base](
    db: Session,
    model: type[T],
    query: Select[*tuple[Any, ...]],
    *,
    page: int,
    page_size: int,
    order: tuple[tuple[str, bool], ...],
) -> tuple[list[T], int]:
    rows = db.execute(
        page_statement(model, query, page=page, page_size=page_size, order=order)
    ).all()
    return [row[0] for row in rows if row[0] is not None], rows[0][-1]
