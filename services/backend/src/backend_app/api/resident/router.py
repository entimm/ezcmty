from fastapi import APIRouter

from backend_app.api.resident.billing import create_resident_billing_router
from backend_app.api.resident.house_claims import create_resident_house_claim_router
from backend_app.api.resident.identity import create_resident_identity_router
from backend_app.api.resident.payments import create_resident_payment_router


def create_resident_router() -> APIRouter:
    router = APIRouter()
    router.include_router(create_resident_identity_router())
    router.include_router(create_resident_house_claim_router())
    router.include_router(create_resident_billing_router())
    router.include_router(create_resident_payment_router())
    return router
