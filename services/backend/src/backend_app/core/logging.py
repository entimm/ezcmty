import json
import logging
import re
from collections import deque
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

request_id_context: ContextVar[str] = ContextVar("request_id", default="-")


def log_exception(exc: BaseException, *, code: str) -> None:
    diagnostics: list[dict[str, Any]] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen and len(diagnostics) < 8:
        seen.add(id(current))
        frames: deque[dict[str, object]] = deque(maxlen=20)
        traceback = current.__traceback__
        while traceback is not None:
            frame = traceback.tb_frame
            module = frame.f_globals.get("__name__", "unknown")
            if not isinstance(module, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*", module):
                module = "unknown"
            frames.append(
                {"module": module, "function": frame.f_code.co_name, "line": traceback.tb_lineno}
            )
            traceback = traceback.tb_next
        diagnostics.append({"error_type": type(current).__name__, "frames": list(frames)})
        current = current.__cause__ or (
            None if current.__suppress_context__ else current.__context__
        )
    logging.getLogger(__name__).error(
        "request_failed code=%s diagnostics=%s", code, json.dumps(diagnostics)
    )


def configure_logging(level: str, service_name: str) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter(service_name))
    logging.basicConfig(level=level, handlers=[handler], force=True)
    # Third-party HTTP debug logs may include URL credentials or query tokens.
    for name in ("httpx", "httpcore", "redis", "sqlalchemy.engine"):
        logging.getLogger(name).setLevel(logging.WARNING)


class JsonFormatter(logging.Formatter):
    def __init__(self, service_name: str) -> None:
        super().__init__()
        self.service_name = service_name

    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(
            {
                "time": datetime.fromtimestamp(record.created, UTC).isoformat(),
                "level": record.levelname,
                "service": self.service_name,
                "logger": record.name,
                "request_id": getattr(record, "request_id", request_id_context.get()),
                "message": record.getMessage(),
            },
            ensure_ascii=False,
        )
