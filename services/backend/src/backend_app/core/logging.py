import json
import logging
from contextvars import ContextVar
from datetime import UTC, datetime

request_id_context: ContextVar[str] = ContextVar("request_id", default="-")


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
