from typing import Literal

from backend_app.core.logging import log_exception
from backend_app.core.redis import get_redis
from backend_app.repositories.system import check_database_connection


def check_readiness() -> dict[str, Literal["ok", "unavailable"]]:
    dependencies: dict[str, Literal["ok", "unavailable"]] = {}
    try:
        check_database_connection()
        dependencies["postgresql"] = "ok"
    except Exception as exc:
        dependencies["postgresql"] = "unavailable"
        log_exception(exc, code="system.dependency_unavailable")
    try:
        get_redis().ping()
        dependencies["redis"] = "ok"
    except Exception as exc:
        dependencies["redis"] = "unavailable"
        log_exception(exc, code="system.dependency_unavailable")
    return dependencies
