from fastapi import APIRouter

from backend_app.api.webhook.payments import create_payment_webhook_router


def create_webhook_router() -> APIRouter:
    router = APIRouter()
    router.include_router(create_payment_webhook_router())
    return router
