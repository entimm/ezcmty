from collections.abc import Iterator
from typing import Any
from urllib.parse import quote

from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask

from backend_app.core.openapi import get_problem_responses, get_request_id_headers
from backend_app.integrations.import_files.storage import safe_download_name
from backend_app.services.imports.artifacts import FileDownload


def import_responses(
    success: int, *errors: int, download: bool = False
) -> dict[int | str, dict[str, Any]]:
    headers = {
        **get_request_id_headers(),
        "Cache-Control": {"schema": {"type": "string", "const": "no-store"}},
    }
    result = get_problem_responses(*errors)
    for status in errors:
        result[status]["headers"] = dict(headers)
        if status == 429:
            result[status]["headers"]["Retry-After"] = {"schema": {"type": "integer", "minimum": 1}}
    result[success] = {"headers": dict(headers)}
    if download:
        result[success]["headers"].update(
            {
                "Content-Disposition": {"schema": {"type": "string", "minLength": 1}},
                "Content-Length": {"schema": {"type": "integer", "minimum": 0}},
                "X-Content-Type-Options": {"schema": {"type": "string", "const": "nosniff"}},
            }
        )
        result[success]["content"] = {
            media: {"schema": {"type": "string", "format": "binary"}}
            for media in (
                "text/csv; charset=utf-8",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        }
    return result


def file_response(download: FileDownload) -> StreamingResponse:
    def chunks() -> Iterator[bytes]:
        try:
            yield from iter(lambda: download.source.read(65536), b"")
        finally:
            download.source.close()

    safe = safe_download_name(download.filename)
    extension = safe.rsplit(".", 1)[-1]
    return StreamingResponse(
        chunks(),
        media_type=download.media_type,
        background=BackgroundTask(download.source.close),
        headers={
            "Content-Disposition": (
                f"attachment; filename=\"import.{extension}\"; filename*=UTF-8''{quote(safe)}"
            ),
            "Content-Length": str(download.size_bytes),
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
