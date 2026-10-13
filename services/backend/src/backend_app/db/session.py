import sys
from collections.abc import Generator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend_app.core.config import get_settings
from backend_app.core.logging import log_exception


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    return create_engine(
        get_settings().database_url.get_secret_value(),
        pool_pre_ping=True,
        pool_recycle=1800,
        hide_parameters=True,
        connect_args={"connect_timeout": 3, "read_timeout": 3, "write_timeout": 3},
    )


@lru_cache(maxsize=1)
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), autoflush=False, autocommit=False)


def get_database_session() -> Generator[Session, None, None]:
    session = get_session_factory()()
    try:
        try:
            yield session
        except BaseException:
            try:
                session.rollback()
            except Exception as exc:
                log_exception(exc, code="INTERNAL_ERROR")
            raise
    finally:
        # Cleanup must not replace an exception already propagating from the service.
        pending_error = sys.exc_info()[0] is not None
        try:
            session.close()
        except Exception as exc:
            if not pending_error:
                raise
            log_exception(exc, code="INTERNAL_ERROR")
