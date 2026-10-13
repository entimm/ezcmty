from typing import Literal

from backend_app.core.redis import get_redis
from backend_app.repositories.system import check_database_connection


def check_readiness() -> dict[str, Literal["ok", "unavailable"]]:
    dependencies: dict[str, Literal["ok", "unavailable"]] = {}
    try:
        check_database_connection()
        dependencies["mysql"] = "ok"
    except Exception:
        dependencies["mysql"] = "unavailable"
    try:
        get_redis().ping()
        dependencies["redis"] = "ok"
    except Exception:
        dependencies["redis"] = "unavailable"
    return dependencies
