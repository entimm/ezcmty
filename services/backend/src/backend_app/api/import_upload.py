"""Bound multipart transport before Starlette can spool an unbounded source upload."""

from starlette.datastructures import Headers
from starlette.formparsers import MultiPartException
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from backend_app.core.exception_handlers import create_problem_response
from backend_app.integrations.import_files.storage import MAX_SOURCE_BYTES

MAX_MULTIPART_BYTES = MAX_SOURCE_BYTES + 64 * 1024


class ImportUploadLimitMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        root_path = scope.get("root_path", "")
        if root_path and path.startswith(root_path + "/"):
            path = path[len(root_path) :]
        if (
            scope["type"] != "http"
            or scope["method"] != "POST"
            or not path.startswith("/v1/import-batches/")
            or not path.endswith("/source-file")
        ):
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        length = headers.get("content-length")
        if length and length.isdigit() and int(length) > MAX_MULTIPART_BYTES:
            response = create_problem_response(
                Request(scope), "import.file_too_large", headers={"Cache-Control": "no-store"}
            )
            await response(scope, receive, send)
            return
        received = 0
        exceeded = False

        async def bounded_receive() -> Message:
            nonlocal received, exceeded
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > MAX_MULTIPART_BYTES:
                    exceeded = True
                    # Starlette closes every spooled file when multipart parsing fails.
                    raise MultiPartException("Source upload exceeds transport bound")
            return message

        async def bounded_send(message: Message) -> None:
            if not exceeded:
                await send(message)

        try:
            await self.app(scope, bounded_receive, bounded_send)
        except MultiPartException:
            if not exceeded:
                raise
        if exceeded:
            response = create_problem_response(
                Request(scope), "import.file_too_large", headers={"Cache-Control": "no-store"}
            )
            await response(scope, receive, send)
