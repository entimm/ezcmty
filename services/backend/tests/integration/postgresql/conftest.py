from __future__ import annotations

import os
import shutil
import subprocess
import time
from collections.abc import Iterator
from contextlib import ExitStack
from pathlib import Path

import pytest
from devtools.seed.bootstrap import SeedSettings
from devtools.seed.config import Plan
from devtools.seed.runner import run
from pytest import MonkeyPatch
from redis import Redis
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from tests.support.billing_services import BillingSetup
from tests.support.house_claims import ClaimSetup, provision_claim
from tests.support.housing_services import provision_housing
from tests.support.paths import BACKEND_ROOT
from tests.support.postgresql import free_port, stop_service
from tests.support.seed import SeedRun

from backend_app.core.admin_sessions import AdminSessionStore
from backend_app.core.config import get_settings
from backend_app.schemas.housing import HouseCreate
from backend_app.services.property_admin.housing import PropertyHousingService


@pytest.fixture(scope="session")
def real_redis() -> Iterator[Redis[str]]:
    if os.environ.get("APP_RUN_POSTGRESQL_TESTS") != "1":
        pytest.skip("Set APP_RUN_POSTGRESQL_TESTS=1 for isolated PostgreSQL/Redis tests")
    binary = shutil.which("redis-server")
    if not binary:
        pytest.fail("Requested PostgreSQL/Redis tests require redis-server on PATH")
    port = free_port()
    with ExitStack() as cleanup:
        process = subprocess.Popen(
            [
                binary,
                "--bind",
                "127.0.0.1",
                "--port",
                str(port),
                "--save",
                "",
                "--appendonly",
                "no",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        cleanup.callback(stop_service, process)
        client: Redis[str] = Redis.from_url(
            f"redis://127.0.0.1:{port}/0",
            decode_responses=True,
            socket_connect_timeout=1,
            socket_timeout=2,
        )
        cleanup.callback(client.close)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if process.poll() is not None:
                pytest.fail("Isolated Redis exited during startup")
            try:
                client.ping()
                break
            except Exception:
                time.sleep(0.1)
        else:
            pytest.fail("Isolated Redis startup timed out")
        yield client


@pytest.fixture
def real_admin(
    migrated_database_url: str,
    real_redis: Redis[str],
    monkeypatch: MonkeyPatch,
) -> Iterator[tuple[sessionmaker[Session], AdminSessionStore]]:
    real_redis.flushdb()
    engine = create_engine(
        migrated_database_url,
        hide_parameters=True,
        connect_args={"options": "-c timezone=UTC"},
    )
    try:
        yield (
            sessionmaker(bind=engine, autoflush=False),
            AdminSessionStore(real_redis, get_settings()),
        )
    finally:
        engine.dispose()
        real_redis.flushdb()


@pytest.fixture
def billing_setup(real_admin: tuple[sessionmaker[Session], AdminSessionStore]) -> BillingSetup:
    factory, store = real_admin
    setup = provision_housing(factory, store)
    with factory() as db:
        house = PropertyHousingService(db).create_house(
            setup.context,
            setup.community_id,
            HouseCreate(space_node_id=setup.node_id, room_no="101"),
            "house",
        )
    return BillingSetup(factory, setup, house.id)


@pytest.fixture
def claim_setup(real_admin: tuple[sessionmaker[Session], AdminSessionStore]) -> ClaimSetup:
    return provision_claim(*real_admin)


@pytest.fixture
def seed_run(
    real_admin: tuple[sessionmaker[Session], AdminSessionStore], tmp_path: Path
) -> SeedRun:
    factory, original_store = real_admin
    settings = original_store.settings.model_copy(update={"env": "test", "admin_login_limit": 1000})

    def start(plan: Plan | None = None, resume: str | None = None) -> Path:
        return run(
            plan=plan,
            resume=resume,
            root=tmp_path / "seed",
            backend_root=BACKEND_ROOT,
            factory=factory,
            client=original_store.client,
            settings=settings,
            seed=SeedSettings(enabled=True, login_name=None, password=None),
        )

    return start
