import signal
from threading import Event

from backend_app.core.config import get_settings
from backend_app.core.logging import configure_logging
from backend_app.tasks.runner import run_worker


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, "worker")
    stop_event = Event()
    signal.signal(signal.SIGINT, lambda *_: stop_event.set())
    signal.signal(signal.SIGTERM, lambda *_: stop_event.set())
    run_worker(stop_event)


if __name__ == "__main__":
    main()
