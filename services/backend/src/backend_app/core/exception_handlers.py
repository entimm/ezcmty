from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import RedisError
from redis.exceptions import TimeoutError as RedisTimeoutError
from sqlalchemy.exc import DisconnectionError, OperationalError, SQLAlchemyError
from sqlalchemy.exc import TimeoutError as DatabaseTimeoutError
from starlette.exceptions import HTTPException

from backend_app.core.error_catalog import ERROR_CATALOG, ERROR_TYPE_PREFIX
from backend_app.core.errors import AppError
from backend_app.core.logging import log_exception
from backend_app.schemas.problem import ProblemDetails, ValidationIssue

# HTTP exceptions use these generic types, even when business codes share a status.
HTTP_ERROR_CODES = (
    "request.bad_request",
    "auth.unauthenticated",
    "auth.forbidden",
    "resource.not_found",
    "request.method_not_allowed",
    "resource.conflict",
    "VALIDATION_ERROR",
    "INTERNAL_ERROR",
    "system.dependency_unavailable",
)


def is_dependency_unavailable(exc: Exception) -> bool:
    if isinstance(
        exc, (RedisConnectionError, RedisTimeoutError, DisconnectionError, DatabaseTimeoutError)
    ):
        return True
    if isinstance(exc, OperationalError):
        # MySQL connection limits, connection failures and lost connections only.
        code = exc.orig.args[0] if exc.orig is not None and exc.orig.args else None
        return exc.connection_invalidated or (
            type(code) is int and code in {1040, 1203, 2002, 2003, 2006, 2013}
        )
    return False


def create_problem_response(
    request: Request,
    code: str,
    *,
    status_code: int | None = None,
    public_detail: str | None = None,
    errors: list[ValidationIssue] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    standard_status, title = ERROR_CATALOG[code]
    status = standard_status if standard_status is not None else status_code
    if status is None or not 400 <= status <= 599:
        raise ValueError("Problem Details requires a valid error status")
    request_id = request.state.request_id
    payload: dict[str, Any] = {
        "type": ERROR_TYPE_PREFIX + code,
        "title": title,
        "status": status,
        "detail": title if public_detail is None else public_detail,
        "instance": "urn:request:" + request_id,
        "code": code,
        "request_id": request_id,
    }
    if errors is not None:
        payload["errors"] = errors
    problem = ProblemDetails.model_validate(payload)
    response_headers = dict(headers or {})
    return JSONResponse(
        status_code=status,
        content=problem.model_dump(exclude_unset=True),
        media_type="application/problem+json",
        headers=response_headers,
    )


async def handle_app_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)
    if exc.status_code >= 500:
        log_exception(exc, code=exc.code)
    return create_problem_response(request, exc.code, public_detail=exc.public_detail)


async def handle_validation_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    errors = [
        ValidationIssue(location=list(error["loc"]), type=error["type"]) for error in exc.errors()
    ]
    return create_problem_response(request, "VALIDATION_ERROR", errors=errors)


async def handle_http_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, HTTPException)
    if not 400 <= exc.status_code <= 599:
        return await handle_system_error(request, exc)
    code = next(
        (code for code in HTTP_ERROR_CODES if ERROR_CATALOG[code][0] == exc.status_code),
        "HTTP_ERROR",
    )
    if exc.status_code >= 500:
        log_exception(exc, code=code)
    return create_problem_response(request, code, status_code=exc.status_code, headers=exc.headers)


async def handle_system_error(request: Request, exc: Exception) -> JSONResponse:
    code = "system.dependency_unavailable" if is_dependency_unavailable(exc) else "INTERNAL_ERROR"
    log_exception(exc, code=code)
    return create_problem_response(request, code)


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, handle_app_error)
    app.add_exception_handler(RequestValidationError, handle_validation_error)
    app.add_exception_handler(HTTPException, handle_http_error)
    app.add_exception_handler(SQLAlchemyError, handle_system_error)
    app.add_exception_handler(RedisError, handle_system_error)
