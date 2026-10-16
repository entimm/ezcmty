from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from devtools.seed.config import EXCLUDED_TABLES, SeedError, resolve_plan
from devtools.seed.repository import coverage
from devtools.seed.state import COLUMNS, State, file_lock
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, sessionmaker
from tests.support.paths import BACKEND_ROOT
from tests.support.seed import SeedRun, totals

from backend_app.core.admin_security import verify_password
from backend_app.core.admin_sessions import AdminSessionStore
from backend_app.models.admin import AdminAccount, AdminAuditLog
from backend_app.models.housing import House, HouseOwner


def test_all_scenarios_cover_tables_append_and_export_usable_credentials(
    seed_run: SeedRun,
    real_admin: tuple[sessionmaker[Session], AdminSessionStore],
) -> None:
    factory, _ = real_admin
    plan = resolve_plan(["admin", "property", "housing", "billing"], workers=2)
    directory = seed_run(plan)
    first = totals(factory)
    assert all(count > 0 for table, count in first.items() if table not in EXCLUDED_TABLES)
    assert first["houses"] == plan.counts()["houses"]
    assert first["house_owners"] == plan.counts()["owners"]
    client = real_admin[1].client
    assert list(client.scan_iter(match="app:seed:admin-login:*"))
    assert not list(client.scan_iter(match="app:admin-login:*"))
    assert not list(client.scan_iter(match="app:session:*"))
    accounts = json.loads((directory / "accounts.json").read_text())
    with factory() as db:
        for item in accounts:
            assert tuple(item) == COLUMNS
            account = db.scalar(
                select(AdminAccount).where(
                    AdminAccount.scope == item["登录端"],
                    AdminAccount.login_name == item["登录名"],
                )
            )
            assert account is not None and verify_password(account.password_hash, item["密码"])
        assert db.scalar(select(func.count()).select_from(House).where(House.enabled.is_(False)))
        assert db.scalar(
            select(func.count()).select_from(HouseOwner).where(HouseOwner.enabled.is_(False))
        )
    seed_run(resume=directory.name)
    assert totals(factory) == first
    second_directory = seed_run(plan)
    second = totals(factory)
    assert directory != second_directory
    assert second["houses"] == 2 * first["houses"]
    assert second["admin_accounts"] == 2 * first["admin_accounts"] - 1
    assert (directory / "accounts.json").stat().st_mode & 0o777 == 0o600
    assert (directory / "context.sqlite3").stat().st_mode & 0o777 == 0o600
    assert directory.stat().st_mode & 0o777 == 0o700


@pytest.mark.parametrize(
    "interrupted_key",
    [
        "bootstrap",
        "bootstrap/password",
        "property/0",
        "property/0/account/0",
        "property/0/account/0/password",
        "housing/0/0/building/0/house/0",
        "housing/0/0/building/0/house/0/owner/0",
    ],
)
def test_resume_after_database_commit_recovers_without_duplicate_writes(
    seed_run: SeedRun,
    real_admin: tuple[sessionmaker[Session], AdminSessionStore],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    interrupted_key: str,
) -> None:
    original = State.complete
    fired = False

    def fail_once(
        self: State, key: str, result: dict[str, Any], account: dict[str, str] | None = None
    ) -> None:
        nonlocal fired
        if key == interrupted_key and not fired:
            fired = True
            raise RuntimeError("simulated process interruption after service commit")
        original(self, key, result, account)

    monkeypatch.setattr(State, "complete", fail_once)
    plan = resolve_plan(
        ["housing"],
        overrides=[
            "housing.buildings_per_community=1",
            "housing.units_per_building=0",
            "housing.houses_per_building=2",
            "housing.phases_per_community=0",
        ],
    )
    with pytest.raises(RuntimeError):
        seed_run(plan)
    directory = next(path.parent for path in (tmp_path / "seed").glob("*/state.json"))
    seed_run(resume=directory.name)
    assert fired
    factory, _ = real_admin
    result = totals(factory)
    assert result["houses"] == 2
    assert result["house_owners"] == 4
    assert result["admin_accounts"] == 2
    with factory() as db:
        duplicates = db.execute(
            select(AdminAuditLog.request_id, AdminAuditLog.action, func.count())
            .where(AdminAuditLog.request_id.like("seed:%"))
            .group_by(AdminAuditLog.request_id, AdminAuditLog.action)
            .having(func.count() > 1)
        ).all()
        assert not duplicates
        for item in json.loads((directory / "accounts.json").read_text()):
            account = db.scalar(
                select(AdminAccount).where(AdminAccount.login_name == item["登录名"])
            )
            assert account is not None and verify_password(account.password_hash, item["密码"])
    before = totals(factory)
    seed_run(resume=directory.name)
    assert totals(factory) == before


def test_resume_refuses_external_mutation(
    seed_run: SeedRun, real_admin: tuple[sessionmaker[Session], AdminSessionStore]
) -> None:
    directory = seed_run(resolve_plan(["housing"], overrides=["housing.owners_per_house=0"]))
    factory, _ = real_admin
    with factory() as db:
        house = db.scalar(select(House))
        assert house is not None
        house.room_no = "external-change"
        db.commit()
    with pytest.raises(SeedError, match="外部变化"):
        seed_run(resume=directory.name)


def test_unknown_database_table_fails_coverage(
    real_admin: tuple[sessionmaker[Session], AdminSessionStore],
) -> None:
    factory, _ = real_admin
    engine = factory.kw["bind"]
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE future_business_table (id integer PRIMARY KEY)"))
    with pytest.raises(SeedError, match="future_business_table"):
        coverage(engine)


def test_batch_lock_rejects_concurrent_resume(tmp_path: Path) -> None:
    with file_lock(tmp_path / "lock"), pytest.raises(SeedError, match="正在执行"):
        with file_lock(tmp_path / "lock"):
            pytest.fail("concurrent lock was accepted")


def test_resume_retries_intent_that_never_reached_service(
    seed_run: SeedRun,
    real_admin: tuple[sessionmaker[Session], AdminSessionStore],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from devtools.seed import runtime

    original = runtime.invoke
    fired = False

    def fail_once(*args: Any, **kwargs: Any) -> str:
        nonlocal fired
        if args[3] == "property.house.create" and not fired:
            fired = True
            raise RuntimeError("interrupted before business operation")
        return original(*args, **kwargs)

    monkeypatch.setattr(runtime, "invoke", fail_once)
    plan = resolve_plan(["housing"], overrides=["housing.owners_per_house=0"])
    with pytest.raises(RuntimeError):
        seed_run(plan)
    directory = next(path.parent for path in (tmp_path / "seed").glob("*/state.json"))
    seed_run(resume=directory.name)
    assert totals(real_admin[0])["houses"] == plan.counts()["houses"]
    assert totals(real_admin[0])["house_owners"] == 0


def test_resume_rejects_changed_database_and_scenario_version(seed_run: SeedRun) -> None:
    directory = seed_run(resolve_plan(["admin"], overrides=["admin.accounts=0"]))
    path = directory / "state.json"
    metadata = json.loads(path.read_text())
    original = metadata["database"]
    metadata["database"] = "different-database"
    path.write_text(json.dumps(metadata))
    with pytest.raises(SeedError, match="目标数据库"):
        seed_run(resume=directory.name)
    metadata["database"] = original
    metadata["plan"]["versions"]["admin"] += 1
    path.write_text(json.dumps(metadata))
    with pytest.raises(SeedError, match="场景版本"):
        seed_run(resume=directory.name)


def test_context_missing_or_corrupt_never_recreates_batch(seed_run: SeedRun) -> None:
    directory = seed_run(resolve_plan(["admin"], overrides=["admin.accounts=0"]))
    path = directory / "context.sqlite3"
    saved = path.read_bytes()
    path.unlink()
    with pytest.raises(SeedError, match="缺少批次上下文"):
        seed_run(resume=directory.name)
    path.write_bytes(saved)
    # A corrupt format must fail rather than silently initialize an empty context.
    path.write_bytes(b"invalid-context")
    import sqlite3

    with pytest.raises(sqlite3.DatabaseError):
        seed_run(resume=directory.name)


@pytest.mark.slow
def test_thousand_houses_have_exact_counts_and_resume_without_growth(
    seed_run: SeedRun,
    real_admin: tuple[sessionmaker[Session], AdminSessionStore],
) -> None:
    plan = resolve_plan(
        ["housing"],
        overrides=[
            "property.companies=2",
            "housing.phases_per_community=0",
            "housing.buildings_per_community=1",
            "housing.units_per_building=2",
            "housing.houses_per_building=0",
            "housing.houses_per_unit=250",
            "housing.owners_per_house=2",
        ],
        workers=2,
    )
    directory = seed_run(plan)
    counts = totals(real_admin[0])
    assert counts["houses"] == 1000
    assert counts["house_owners"] == 2000
    report = json.loads((directory / "report.json").read_text())
    print(
        "SEED_SCALE_RESULT",
        json.dumps(
            {
                key: report[key]
                for key in (
                    "tables",
                    "steps",
                    "elapsed_seconds",
                )
            }
        ),
    )
    seed_run(resume=directory.name)
    assert totals(real_admin[0]) == counts


def test_cli_survives_process_exit_after_password_commit(
    real_admin: tuple[sessionmaker[Session], AdminSessionStore],
    tmp_path: Path,
) -> None:
    import os
    import subprocess
    import sys

    factory, store = real_admin
    redis_parameters = store.client.connection_pool.connection_kwargs
    environment = {
        **os.environ,
        "APP_ENV": "test",
        "APP_DATABASE_URL": factory.kw["bind"].url.render_as_string(hide_password=False),
        "APP_REDIS_URL": f"redis://127.0.0.1:{redis_parameters['port']}/0",
        "APP_ADMIN_LOGIN_LIMIT": "1000",
        "SEED_ENABLED": "1",
        "SEED_TEST_ROOT": str(tmp_path),
    }
    # Empty overrides also isolate the child from credentials in the developer's .env.
    environment["SEED_LOGIN_NAME"] = ""
    environment["SEED_PASSWORD"] = ""
    script = """
import os
import sys
from pathlib import Path
from devtools.seed import __main__ as cli
from devtools.seed.state import State
cli.REPOSITORY_ROOT = Path(os.environ["SEED_TEST_ROOT"])
original = State.complete
if sys.argv[1] == "run":
    def crash(self, key, result, account=None):
        if key == "property/0/account/0/password":
            os._exit(73)
        original(self, key, result, account)
    State.complete = crash
sys.exit(cli.main(sys.argv[1:]))
"""
    crashed = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            "run",
            "--scenario",
            "housing",
            "--set",
            "housing.houses_per_unit=0",
            "--set",
            "housing.owners_per_house=0",
        ],
        cwd=BACKEND_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert crashed.returncode == 73, crashed.stderr
    root = tmp_path / ".dev" / "seed"
    directory = next(path.parent for path in root.glob("*/state.json"))
    assert not (directory / "accounts.json").exists()
    resumed = subprocess.run(
        [sys.executable, "-c", script, "resume", directory.name],
        cwd=BACKEND_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert resumed.returncode == 0, resumed.stderr
    assert totals(factory)["admin_accounts"] == 2
    for account in json.loads((directory / "accounts.json").read_text()):
        assert (
            account["密码"] not in crashed.stdout + crashed.stderr + resumed.stdout + resumed.stderr
        )
    assert json.loads((directory / "state.json").read_text())["status"] == "complete"


def test_resume_rejects_modified_quantity_parameters(seed_run: SeedRun) -> None:
    directory = seed_run(resolve_plan(["admin"], overrides=["admin.accounts=0"]))
    path = directory / "state.json"
    metadata = json.loads(path.read_text())
    metadata["plan"]["parameters"]["admin"]["accounts"] = 5
    path.write_text(json.dumps(metadata))
    with pytest.raises(SeedError, match="批次参数"):
        seed_run(resume=directory.name)


def test_resume_validates_system_role_links(
    seed_run: SeedRun,
    real_admin: tuple[sessionmaker[Session], AdminSessionStore],
) -> None:
    from sqlalchemy import delete

    from backend_app.models.admin import AdminAccountRole

    directory = seed_run(
        resolve_plan(
            ["property"],
            overrides=[
                "property.companies=1",
                "property.communities_per_company=1",
                "property.admins_per_company=1",
            ],
        )
    )
    factory, _ = real_admin
    with factory() as db:
        identifier = db.scalar(
            select(AdminAccount.id).where(AdminAccount.scope == "property_admin")
        )
        db.execute(delete(AdminAccountRole).where(AdminAccountRole.account_id == identifier))
        db.commit()
    with pytest.raises(SeedError, match="外部变化"):
        seed_run(resume=directory.name)


def test_resume_initializes_context_after_exit_before_first_step(
    seed_run: SeedRun,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = State.__init__

    def interrupt(
        self: State, directory: Path, *, create: bool = False, initialize: bool = False
    ) -> None:
        raise RuntimeError("exit before context initialization")

    monkeypatch.setattr(State, "__init__", interrupt)
    with pytest.raises(RuntimeError):
        seed_run(resolve_plan(["admin"], overrides=["admin.accounts=0"]))
    directory = next(path.parent for path in (tmp_path / "seed").glob("*/state.json"))
    assert not (directory / "context.sqlite3").exists()
    monkeypatch.setattr(State, "__init__", original)
    seed_run(resume=directory.name)
    assert json.loads((directory / "state.json").read_text())["status"] == "complete"
