from pydantic import BaseModel, Field

from backend_app.core.error_catalog import REQUEST_ID_PATTERN


class ValidationIssue(BaseModel):
    location: list[str | int]
    type: str


class ProblemDetails(BaseModel):
    type: str = Field(json_schema_extra={"format": "uri"})
    title: str
    status: int = Field(ge=400, le=599)
    detail: str
    instance: str = Field(json_schema_extra={"format": "uri"})
    code: str
    request_id: str = Field(pattern=REQUEST_ID_PATTERN)
    errors: list[ValidationIssue] = Field(default_factory=list)
