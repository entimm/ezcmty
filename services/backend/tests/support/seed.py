from collections.abc import Callable
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from backend_app.db.base import Base

SeedRun = Callable[..., Path]


def totals(factory: sessionmaker[Session]) -> dict[str, int]:
    with factory() as db:
        return {
            table.name: int(db.scalar(select(func.count()).select_from(table)) or 0)
            for table in Base.metadata.sorted_tables
        }
