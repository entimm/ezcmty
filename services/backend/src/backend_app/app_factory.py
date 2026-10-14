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
    runtime = service_name.replace("-", "_")
    if runtime in {"platform_admin_api", "property_admin_api"}:
        from backend_app.api.admin import create_admin_router

        if runtime == "platform_admin_api":
            app.include_router(create_admin_router("platform_admin"))
        else:
            app.include_router(create_admin_router("property_admin", include_management=False))
    configure_openapi(app)
    return app
