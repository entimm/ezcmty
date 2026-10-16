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
    app.add_middleware(RequestIdMiddleware, no_store=service_name == "resident-api")
    register_exception_handlers(app)
    app.include_router(create_system_router(service_name))
    runtime = service_name.replace("-", "_")
    if runtime == "platform_admin_api":
        from backend_app.api.platform_admin.router import create_platform_admin_router

        app.include_router(create_platform_admin_router())
    elif runtime == "property_admin_api":
        from backend_app.api.property_admin.router import create_property_admin_router

        app.include_router(create_property_admin_router())
    elif runtime == "resident_api":
        from backend_app.api.resident.house_claims import create_resident_house_claim_router
        from backend_app.api.resident.identity import create_resident_identity_router

        app.include_router(create_resident_identity_router())
        app.include_router(create_resident_house_claim_router())
    configure_openapi(app)
    return app
