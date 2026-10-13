from typing import Literal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str


class ReadinessResponse(BaseModel):
    status: Literal["ok", "not_ready"]
    service: str
    dependencies: dict[str, Literal["ok", "unavailable"]]


class ErrorResponse(BaseModel):
    code: str
    message: str
    request_id: str
    details: dict[str, object] = Field(default_factory=dict)
