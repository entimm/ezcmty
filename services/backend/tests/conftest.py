from __future__ import annotations

from collections.abc import Generator, Iterator
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from pytest import MonkeyPatch

from backend_app.core.config import get_settings
from backend_app.core.error_catalog import CONTRACT_VERSION
from backend_app.core.redis import get_redis
from backend_app.db.session import get_engine, get_session_factory

if TYPE_CHECKING:
    from _pytest.terminal import TerminalReporter

INCOMPLETE = pytest.StashKey[set[str]]()
TESTS_ROOT = Path(__file__).resolve().parent


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--require-all-tests",
        action="store_true",
        help="Fail verification when selected tests are skipped or marked as expected failures",
    )


def pytest_configure(config: pytest.Config) -> None:
    config.stash[INCOMPLETE] = set()


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if not item.path.is_relative_to(TESTS_ROOT):
            continue
        parts = item.path.relative_to(TESTS_ROOT).parts
        if parts[0] in {"unit", "integration", "contract"}:
            item.add_marker(getattr(pytest.mark, parts[0]))
        if parts[:2] == ("integration", "mysql"):
            item.add_marker(pytest.mark.mysql)
        if parts[:2] == ("integration", "dev"):
            item.add_marker(pytest.mark.slow)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item, call: pytest.CallInfo[None]
) -> Generator[None, pytest.TestReport, pytest.TestReport]:
    report = yield
    if report.skipped or hasattr(report, "wasxfail"):
        item.config.stash[INCOMPLETE].add(report.nodeid)
    return report


@pytest.hookimpl(wrapper=True)
def pytest_make_collect_report(
    collector: pytest.Collector,
) -> Generator[None, pytest.CollectReport, pytest.CollectReport]:
    report = yield
    if report.skipped:
        collector.config.stash[INCOMPLETE].add(report.nodeid)
    return report


def pytest_sessionfinish(session: pytest.Session) -> None:
    if (
        session.config.getoption("--require-all-tests")
        and session.config.stash[INCOMPLETE]
        and session.exitstatus == pytest.ExitCode.OK
    ):
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


def pytest_terminal_summary(terminalreporter: TerminalReporter, config: pytest.Config) -> None:
    incomplete = config.stash[INCOMPLETE]
    if config.getoption("--require-all-tests") and incomplete:
        terminalreporter.write_sep("=", "Required tests did not complete successfully")
        for nodeid in sorted(incomplete):
            terminalreporter.write_line(nodeid)


@pytest.fixture(autouse=True)
def configure_test_environment(monkeypatch: MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("APP_DATABASE_URL", "mysql+pymysql://127.0.0.1/test")
    monkeypatch.setenv("APP_REDIS_URL", "redis://127.0.0.1:6379/0")
    monkeypatch.setenv("APP_VERSION", CONTRACT_VERSION)
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()
    get_redis.cache_clear()
    try:
        yield
    finally:
        engine = get_engine() if get_engine.cache_info().currsize else None
        redis = get_redis() if get_redis.cache_info().currsize else None
        get_settings.cache_clear()
        get_engine.cache_clear()
        get_session_factory.cache_clear()
        get_redis.cache_clear()
        if engine is not None:
            engine.dispose()
        if redis is not None:
            redis.close()
