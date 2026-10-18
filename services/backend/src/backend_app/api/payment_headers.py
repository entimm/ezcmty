from typing import Annotated

from fastapi import Header, Response

from backend_app.core.errors import AppError


def no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


def required_write_headers(
    origin: Annotated[str, Header(alias="Origin", max_length=2048)],
    csrf_token: Annotated[str, Header(alias="X-CSRF-Token", max_length=256)],
) -> None:
    # Authentication's check_write validates their values against the current session.
    if not origin or not csrf_token:
        raise AppError("auth.csrf_failed")
