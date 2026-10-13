from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str


class ReadinessResponse(BaseModel):
    status: Literal["ok", "not_ready"]
    service: str
    dependencies: dict[str, Literal["ok", "unavailable"]]
