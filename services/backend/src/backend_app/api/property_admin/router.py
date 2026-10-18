from fastapi import APIRouter

from backend_app.api.admin import create_admin_auth_router
from backend_app.api.payment_management import create_payment_management_router
from backend_app.api.property_admin.billing import create_property_billing_router
from backend_app.api.property_admin.house_claims import create_property_house_claim_router
from backend_app.api.property_admin.housing import create_property_housing_router
from backend_app.api.property_admin.payment_configuration import (
    create_property_payment_configuration_router,
)
from backend_app.api.property_admin.workspace import create_property_workspace_router
from backend_app.services.property_admin.admin import PropertyAdminService


def create_property_admin_router() -> APIRouter:
    auth = create_admin_auth_router("property_admin", PropertyAdminService)
    router = APIRouter()
    router.include_router(auth.router)
    router.include_router(create_property_workspace_router(auth.permission))
    router.include_router(create_property_housing_router(auth.permission, auth.check_write))
    router.include_router(create_property_billing_router(auth.permission, auth.check_write))
    router.include_router(create_property_house_claim_router(auth.permission, auth.check_write))
    router.include_router(create_property_payment_configuration_router(auth.permission))
    router.include_router(create_payment_management_router("property_admin", auth.permission))
    return router
