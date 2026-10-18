from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response, Security
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader
from sqlalchemy.orm import Session

from backend_app.core.config import get_settings
from backend_app.db.session import get_database_session
from backend_app.integrations.wechatpay.client import WechatPayClient, WechatPayError
from backend_app.integrations.wechatpay.notifications import Notifications
from backend_app.services.webhook.payments import PaymentWebhookService

signature = APIKeyHeader(
    name="Wechatpay-Signature", scheme_name="WechatpaySignature", auto_error=False
)


def get_notification_verifier() -> Notifications | None:
    try:
        return Notifications(WechatPayClient.from_settings(get_settings()))
    except Exception:
        return None


def envelope_schema(original_type: str) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "id": {"type": "string", "minLength": 1, "maxLength": 64},
            "create_time": {"type": "string", "format": "date-time"},
            "event_type": {"type": "string", "const": "TRANSACTION.SUCCESS"},
            "resource_type": {"type": "string", "const": "encrypt-resource"},
            "summary": {"type": "string"},
            "resource": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "original_type": {"type": "string", "const": original_type},
                    "algorithm": {"type": "string", "const": "AEAD_AES_256_GCM"},
                    "ciphertext": {"type": "string", "minLength": 1},
                    "associated_data": {"type": "string"},
                    "nonce": {"type": "string", "minLength": 1},
                },
                "required": ["original_type", "algorithm", "ciphertext", "nonce"],
            },
        },
        "required": ["id", "create_time", "event_type", "resource_type", "summary", "resource"],
    }


failure_schema = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "code": {"type": "string", "const": "FAIL"},
        "message": {"type": "string", "minLength": 1, "maxLength": 256},
    },
    "required": ["code", "message"],
}


def create_payment_webhook_router() -> APIRouter:
    router = APIRouter(prefix="/webhooks/payments/wechatpay", tags=["payments"])
    responses: dict[int | str, dict[str, Any]] = {
        status: {"content": {"application/json": {"schema": failure_schema}}}
        for status in (400, 401, 500)
    }
    parameters = [
        {"name": name, "in": "header", "required": True, "schema": schema}
        for name, schema in (
            ("Wechatpay-Timestamp", {"type": "string", "pattern": "^[0-9]+$"}),
            ("Wechatpay-Nonce", {"type": "string", "minLength": 1}),
            ("Wechatpay-Serial", {"type": "string", "minLength": 1}),
        )
    ]

    def metadata(kind: str) -> dict[str, Any]:
        return {
            "parameters": parameters,
            "requestBody": {
                "required": True,
                "content": {"application/json": {"schema": envelope_schema(kind)}},
            },
        }

    async def receive(
        request: Request, db: Session, verifier: Notifications | None, kind: str
    ) -> Response:
        try:
            if verifier is None:
                return JSONResponse({"code": "FAIL", "message": "通知暂未保存"}, status_code=500)
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > WechatPayClient.MAX_RESPONSE_BYTES:
                    return JSONResponse(
                        {"code": "FAIL", "message": "通知格式无效"}, status_code=400
                    )
            PaymentWebhookService(db, verifier).receive(kind, request.headers, bytes(body))
            return Response(status_code=204)
        except WechatPayError as error:
            status = 401 if error.code == "INVALID_SIGNATURE" else 400
            return JSONResponse({"code": "FAIL", "message": "通知验证失败"}, status_code=status)
        except Exception:
            return JSONResponse({"code": "FAIL", "message": "通知暂未保存"}, status_code=500)

    @router.post(
        "/payment-success",
        operation_id="receiveWechatPayPaymentSuccess",
        status_code=204,
        response_class=Response,
        responses=responses,
        openapi_extra=metadata("transaction"),
    )
    async def payment(
        request: Request,
        db: Annotated[Session, Depends(get_database_session)],
        verifier: Annotated[Notifications | None, Depends(get_notification_verifier)],
        channel_signature: Annotated[str | None, Security(signature)],
    ) -> Response:
        return await receive(request, db, verifier, "payment")

    @router.post(
        "/profit-sharing",
        operation_id="receiveWechatPayProfitSharingNotification",
        status_code=204,
        response_class=Response,
        responses=responses,
        openapi_extra=metadata("profitsharing"),
    )
    async def sharing(
        request: Request,
        db: Annotated[Session, Depends(get_database_session)],
        verifier: Annotated[Notifications | None, Depends(get_notification_verifier)],
        channel_signature: Annotated[str | None, Security(signature)],
    ) -> Response:
        return await receive(request, db, verifier, "profit_sharing")

    return router
