import asyncio
import json
from typing import Any

import pytest
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import Message, Receive, Scope, Send

from backend_app.api.import_upload import MAX_MULTIPART_BYTES, ImportUploadLimitMiddleware
from backend_app.core.middleware import RequestIdMiddleware


@pytest.mark.parametrize("declared_length", [True, False], ids=["content-length", "chunked"])
def test_source_transport_stops_before_spooling_the_entire_oversized_body(
    declared_length: bool,
) -> None:
    headers = [(b"content-type", b"multipart/form-data; boundary=import-boundary")]
    if declared_length:
        headers.append((b"content-length", str(MAX_MULTIPART_BYTES + 1).encode()))
    scope: Scope = {
        "type": "http",
        "method": "POST",
        "path": "/v1/import-batches/00000000-0000-4000-8000-000000000001/source-file",
        "query_string": b"",
        "headers": headers,
        "state": {},
    }
    receives = 0
    reached_handler = False
    sent: list[Message] = []

    async def receive() -> Message:
        nonlocal receives
        receives += 1
        body = (
            (
                b"--import-boundary\r\nContent-Disposition: form-data; "
                b'name="file"; filename="source.csv"\r\n\r\n'
            )
            if receives == 1
            else b""
        ) + b"x" * (64 * 1024)
        return {"type": "http.request", "body": body, "more_body": True}

    async def inner(scope: Scope, receive: Receive, send: Send) -> None:
        nonlocal reached_handler
        request = Request(scope, receive)
        try:
            async with request.form():
                reached_handler = True
            await Response(status_code=204)(scope, receive, send)
        except HTTPException:
            await Response(status_code=400)(scope, receive, send)

    async def send(message: Message) -> None:
        sent.append(message)

    app = RequestIdMiddleware(ImportUploadLimitMiddleware(inner))
    asyncio.run(app(scope, receive, send))
    assert not reached_handler
    assert receives < 170
    start = next(m for m in sent if m["type"] == "http.response.start")
    assert start["status"] == 413
    response_headers = dict(start["headers"])
    assert response_headers[b"cache-control"] == b"no-store"
    assert response_headers[b"x-request-id"]
    payload: dict[str, Any] = json.loads(
        b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    )
    assert payload["code"] == "import.file_too_large"
