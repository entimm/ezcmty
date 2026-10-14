from fastapi import FastAPI

from backend_app.core.config import get_settings
from backend_app.core.exception_handlers import register_exception_handlers
from backend_app.core.logging import configure_logging
from backend_app.core.middleware import RequestIdMiddleware
from backend_app.core.openapi import configure_openapi
from backend_app.core.system_routes import create_system_router


def create_app(service_name: str) -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level, service_name)

    app = FastAPI(
        title=settings.name,
        version=settings.version,
        description=f"{service_name} API",
    )
    app.add_middleware(RequestIdMiddleware)
    register_exception_handlers(app)
    app.include_router(create_system_router(service_name))
    if service_name.replace("-", "_") == "platform_admin_api":
        from backend_app.api.admin import create_admin_router

        app.include_router(create_admin_router("platform_admin"))
    configure_openapi(app)
    return app
