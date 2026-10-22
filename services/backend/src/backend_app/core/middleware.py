import logging
import re
from time import perf_counter
from uuid import uuid4

from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from backend_app.core.error_catalog import REQUEST_ID_PATTERN
from backend_app.core.exception_handlers import handle_system_error
from backend_app.core.logging import log_exception, request_id_context


class RequestIdMiddleware:
    def __init__(self, app: ASGIApp, *, no_store: bool = False) -> None:
        self.app = app
        self.no_store = no_store

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        supplied_id = next(
            (value for key, value in scope.get("headers", []) if key == b"x-request-id"), b""
        )
        request_id = (
            supplied_id.decode("ascii")
            if re.fullmatch(REQUEST_ID_PATTERN.encode(), supplied_id)
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
                headers = [
                    (key, value)
                    for key, value in message.get("headers", [])
                    if key.lower() != b"x-request-id"
                ]
                headers.append((b"x-request-id", request_id.encode()))
                route_path = getattr(scope.get("route"), "path", "")
                if self.no_store or route_path.startswith(
                    ("/v1/house-claims", "/v1/resident-house-bindings", "/v1/import-")
                ):
                    headers = [(k, v) for k, v in headers if k.lower() != b"cache-control"]
                    headers.append((b"cache-control", b"no-store"))
                message["headers"] = headers
            await send(message)

        logger = logging.getLogger(__name__)
        try:
            await self.app(scope, receive, send_with_request_id)
        except Exception as exc:
            if response_started:
                log_exception(exc, code="INTERNAL_ERROR")
                raise RuntimeError(f"Response aborted; request_id={request_id}") from None
            response = await handle_system_error(Request(scope, receive), exc)
            await response(scope, receive, send_with_request_id)
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
