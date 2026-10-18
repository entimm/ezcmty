import re
from datetime import UTC, datetime
from typing import Annotated, Any

from pydantic import AfterValidator, Field, field_validator

from backend_app.schemas.admin import AdminSchema


def check_idempotency_key(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
        raise ValueError("Invalid idempotency key")
    return value


type IdempotencyKey = Annotated[
    str, Field(min_length=1, max_length=128), AfterValidator(check_idempotency_key)
]


class PaymentSchema(AdminSchema):
    @field_validator("*")
    @classmethod
    def normalize_timestamp(cls, value: Any) -> Any:
        if isinstance(value, datetime):
            if value.tzinfo is None:
                raise ValueError("Timestamp must include a timezone")
            return value.astimezone(UTC)
        return value
