from http import HTTPStatus

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from backend_app.core.config import get_settings
from backend_app.core.errors import AppError
from backend_app.core.logging import configure_logging
from backend_app.core.middleware import RequestIdMiddleware
from backend_app.core.system_routes import create_system_router
from backend_app.schemas.system import ErrorResponse


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "-")


def create_app(service_name: str) -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level, service_name)

    app = FastAPI(
        title=settings.name,
        version=settings.version,
        description=f"{service_name} API",
    )
    app.add_middleware(RequestIdMiddleware)

    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        response = ErrorResponse(
            code=exc.code,
            message=exc.message,
            request_id=_request_id(request),
            details=exc.details,
        )
        return JSONResponse(status_code=exc.status_code, content=response.model_dump())

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        response = ErrorResponse(
            code="VALIDATION_ERROR",
            message="请求参数校验失败",
            request_id=_request_id(request),
            details={
                "errors": [
                    {"location": list(error["loc"]), "type": error["type"]}
                    for error in exc.errors()
                ]
            },
        )
        return JSONResponse(status_code=422, content=response.model_dump())

    @app.exception_handler(HTTPException)
    async def handle_http_error(request: Request, exc: HTTPException) -> JSONResponse:
        response = ErrorResponse(
            code="HTTP_ERROR",
            message=HTTPStatus(exc.status_code).phrase,
            request_id=_request_id(request),
        )
        return JSONResponse(
            status_code=exc.status_code, content=response.model_dump(), headers=exc.headers
        )

    app.include_router(create_system_router(service_name))
    return app
