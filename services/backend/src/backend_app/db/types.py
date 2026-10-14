from uuid import UUID

from sqlalchemy import LargeBinary
from sqlalchemy.dialects.mysql import BINARY
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator

from backend_app.core.identifiers import normalize_uuid


class UUIDBinary(TypeDecorator[str]):
    """Store UUID bytes in RFC order while exposing canonical strings to the application."""

    impl = LargeBinary(16).with_variant(BINARY(16), "mysql")
    cache_ok = True

    @property
    def python_type(self) -> type[str]:
        return str

    def process_bind_param(self, value: str | None, dialect: Dialect) -> bytes | None:
        return UUID(normalize_uuid(value)).bytes if value is not None else None

    def process_result_value(self, value: bytes | None, dialect: Dialect) -> str | None:
        return str(UUID(bytes=value)) if value is not None else None
