from fastapi import APIRouter

from backend_app.api.client.identity import create_client_identity_router
from backend_app.api.client.resident.billing import create_resident_billing_router
from backend_app.api.client.resident.house_claims import create_resident_house_claim_router
from backend_app.api.client.resident.payments import create_resident_payment_router


def create_client_router() -> APIRouter:
    router = APIRouter()
    router.include_router(create_client_identity_router())
    router.include_router(create_resident_house_claim_router())
    router.include_router(create_resident_billing_router())
    router.include_router(create_resident_payment_router())
    return router
