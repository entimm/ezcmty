from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from threading import Event, get_ident
from typing import Any

import pytest
from sqlalchemy.orm import Session

from backend_app.models.admin import utc_now
from backend_app.tasks.runner import LeaseHeartbeat, run_worker
from backend_app.tasks.types import SourceLeaseLost, TaskEnvelope


class FakeSession:
    def __init__(self, factory: FakeFactory) -> None:
        self.factory = factory
        self.owner_thread = get_ident()
        self.closed = False
        self.committed = False

    def __enter__(self) -> FakeSession:
        self.factory.opened.append(self)
        return self

    def __exit__(self, *args: object) -> None:
        self.closed = True

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        pass


class FakeFactory:
    def __init__(self) -> None:
        self.opened: list[FakeSession] = []

    def __call__(self) -> FakeSession:
        return FakeSession(self)


class Source:
    task_count = 1

    def __init__(self, name: str, dispatch: Callable[[TaskEnvelope], None]) -> None:
        self.name = name
        self.handle = dispatch
        self.periodic_checks: Mapping[str, Callable[[], None]] = {}
        self.claims = 0
        self.renewed = Event()
        self.renew_thread = 0
        self.lease_lost = False

    def probe(self, db: Session) -> None:
        pass

    def claim(self, db: Session, *, now: datetime, lease_seconds: int) -> tuple[TaskEnvelope, ...]:
        self.claims += 1
        return (TaskEnvelope(self.name, "type", "target", self.claims, now + timedelta(seconds=3)),)

    def renew(self, db: Session, lease: TaskEnvelope, *, now: datetime, lease_seconds: int) -> None:
        self.renew_thread = get_ident()
        self.renewed.set()
        if self.lease_lost:
            raise SourceLeaseLost

    def dispatch(self, lease: TaskEnvelope) -> None:
        self.handle(lease)

    def close(self) -> None:
        pass


def test_runner_limits_each_source_to_one_dispatch_per_round_and_yields_fairly() -> None:
    stop = Event()
    factory: Any = FakeFactory()
    seen: list[str] = []

    def handle(lease: TaskEnvelope) -> None:
        # Source claims have already committed and closed before business dispatch.
        assert factory.opened[-1].closed and factory.opened[-1].committed
        seen.append(lease.id)
        if len(seen) == 6:
            stop.set()

    payments = Source("payment", handle)
    imports = Source("import", handle)
    run_worker(stop, factory=factory, sources=(payments, imports))
    assert seen == ["payment", "import", "payment", "import", "payment", "import"]
    assert payments.claims == imports.claims == 3


def test_stop_at_safe_dispatch_boundary_does_not_claim_another_source() -> None:
    stop = Event()
    factory: Any = FakeFactory()
    first = Source("payment", lambda lease: stop.set())
    second = Source("import", lambda lease: pytest.fail("Stopped worker dispatched import"))
    run_worker(stop, factory=factory, sources=(first, second))
    assert second.claims == 0


def test_heartbeat_uses_independent_thread_session_and_stops_after_lease_loss() -> None:
    factory: Any = FakeFactory()
    source = Source("import", lambda lease: None)
    source.lease_lost = True
    now = utc_now()
    heartbeat = LeaseHeartbeat(
        factory,
        TaskEnvelope("task", "type", "target", 1, now + timedelta(seconds=3)),
        source=source,
        lease_seconds=3,
        clock=lambda: now,
    )
    heartbeat.start()
    try:
        assert source.renewed.wait(3)
        heartbeat.thread.join(timeout=3)
        assert not heartbeat.thread.is_alive()
        assert source.renew_thread != get_ident()
        assert factory.opened[0].owner_thread == source.renew_thread
        assert factory.opened[0].closed
    finally:
        heartbeat.close()


def test_periodic_failure_does_not_starve_normal_task_sources() -> None:
    stop = Event()
    factory: Any = FakeFactory()
    checks: list[str] = []
    source = Source("import", lambda lease: stop.set())

    def failing_check() -> None:
        checks.append("called")
        raise RuntimeError("synthetic")

    source.periodic_checks = {"import_retention": failing_check}
    run_worker(stop, factory=factory, sources=(source,))
    assert checks == ["called"]
    assert source.claims == 1
