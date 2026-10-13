import logging
import re
from time import perf_counter
from uuid import uuid4

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from backend_app.core.logging import request_id_context
from backend_app.schemas.system import ErrorResponse


class RequestIdMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        supplied_id = next(
            (value for key, value in scope.get("headers", []) if key == b"x-request-id"), b""
        )
        request_id = (
            supplied_id.decode("ascii")
            if re.fullmatch(rb"[A-Za-z0-9_-]{1,64}", supplied_id)
            else uuid4().hex
        )
        scope.setdefault("state", {})["request_id"] = request_id
        context_token = request_id_context.set(request_id)
        started_at = perf_counter()
        response_started = False
        status_code = 500

        async def send_with_request_id(message: Message) -> None:
            nonlocal response_started, status_code
            if message["type"] == "http.response.start":
                response_started = True
                status_code = message["status"]
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode()))
                message["headers"] = headers
            await send(message)

        logger = logging.getLogger(__name__)
        try:
            await self.app(scope, receive, send_with_request_id)
        except Exception as exc:
            # Exception text and tracebacks may contain credentials or request data.
            logger.error("request_failed error_type=%s", type(exc).__name__)
            if response_started:
                raise
            payload = ErrorResponse(
                code="INTERNAL_ERROR", message="服务内部错误", request_id=request_id
            )
            await JSONResponse(payload.model_dump(), status_code=500)(
                scope, receive, send_with_request_id
            )
        finally:
            route = scope.get("route")
            logger.info(
                "http_request method=%s route=%s status=%s duration_ms=%.1f",
                scope["method"],
                getattr(route, "path", "unmatched"),
                status_code,
                (perf_counter() - started_at) * 1000,
            )
            request_id_context.reset(context_token)
