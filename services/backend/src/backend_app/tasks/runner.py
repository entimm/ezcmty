import logging
from threading import Event


def run_worker(stop_event: Event) -> None:
    """Provide a process lifecycle; task execution is added with concrete task requirements."""
    logger = logging.getLogger(__name__)
    logger.info("worker_started task_handlers=0")
    stop_event.wait()
    logger.info("worker_stopped")
