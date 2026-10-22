from fastapi import APIRouter

from backend_app.api.admin import create_admin_auth_router
from backend_app.api.imports import create_import_router
from backend_app.api.payment_management import create_payment_management_router
from backend_app.api.platform_admin.admin import create_platform_management_router
from backend_app.api.platform_admin.payment_configuration import create_payment_configuration_router
from backend_app.api.platform_admin.payment_recovery import create_payment_recovery_router
from backend_app.api.platform_admin.property import create_property_router
from backend_app.services.platform_admin.admin import PlatformAdminService


def create_platform_admin_router() -> APIRouter:
    auth = create_admin_auth_router("platform_admin", PlatformAdminService)
    router = APIRouter()
    router.include_router(auth.router)
    router.include_router(create_platform_management_router(auth.permission, auth.check_write))
    router.include_router(create_property_router(auth.permission, auth.check_write))
    router.include_router(create_payment_configuration_router(auth.permission, auth.check_write))
    router.include_router(create_payment_management_router("platform_admin", auth.permission))
    router.include_router(create_payment_recovery_router(auth.permission, auth.check_write))
    router.include_router(create_import_router("platform_admin", auth.permission, auth.check_write))
    return router
