from __future__ import annotations

import json
import secrets
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any

from redis import Redis
from sqlalchemy import false, func, or_, select
from sqlalchemy.orm import Session, sessionmaker

from backend_app.core.admin_sessions import AdminSessionStore
from backend_app.core.config import Settings
from backend_app.domain.billing import business_today
from backend_app.models.admin import (
    AdminAccount,
    AdminAccountRole,
    AdminAuditLog,
    AdminRole,
    AdminRolePermission,
)
from backend_app.models.property import PropertyCompany
from devtools.seed.bootstrap import SeedSettings, platform_actor
from devtools.seed.config import REGISTRY, BillingParameters, Plan, SeedError, validate_plan
from devtools.seed.repository import MODELS, coverage, database_fingerprint
from devtools.seed.runtime import Actor, Executor
from devtools.seed.scenarios import admin, billing, housing
from devtools.seed.scenarios import property as property_scenario
from devtools.seed.scenarios.property import Company
from devtools.seed.state import State, file_lock, private_directory, run_directory, save_json

FORMAT_VERSION = 1
REDIS_KEY_PREFIX = "app:seed"


class Progress:
    def __init__(self) -> None:
        self.started = time.monotonic()
        self.reported = self.started
        self.completed = 0
        self.lock = threading.Lock()

    def tick(self) -> None:
        with self.lock:
            self.completed += 1
            now = time.monotonic()
            if now - self.reported >= 5:
                print(
                    f"本次完成 {self.completed} 个步骤，"
                    f"{self.completed / (now - self.started):.1f} 步/秒",
                    flush=True,
                )
                self.reported = now


def guard(settings: Settings, seed: SeedSettings) -> None:
    if "env" not in settings.model_fields_set or settings.env not in {"local", "test"}:
        raise SeedError("seed 只允许显式配置 APP_ENV=local/test")
    if not seed.enabled:
        raise SeedError("请显式设置 SEED_ENABLED=1 后运行 seed")


def reconcile(executor: Executor) -> None:
    for key, spec, data in executor.state.pending():
        if spec["action"].startswith("property.bill."):
            payload = executor.repo.recover_bill(spec, data, executor.request_id(key))
            if payload is not None:
                executor.confirm_bill(key, payload)
            continue
        identifier = executor.repo.recover(spec, spec.get("request_id", executor.request_id(key)))
        if identifier:
            executor.repo.verify(spec["model"], identifier, data["expected"])
            executor.confirm(key, spec, data, identifier)
    for model, identifier, expected in executor.state.entities():
        executor.repo.verify(model, identifier, expected)
    executor.db.rollback()


def execute(
    state: State,
    plan: Plan,
    factory: sessionmaker[Session],
    store: AdminSessionStore,
    seed: SeedSettings,
    root: Path,
    fingerprint: str,
) -> dict[str, Any]:
    stop = threading.Event()
    progress = Progress()
    with factory() as db:
        executor = Executor(state, db, store, stop, progress.tick)
        reconcile(executor)
        if state.marked("complete"):
            return report(state, plan, progress, factory)
        actor = platform_actor(executor, root, fingerprint, seed)
        try:
            if "admin" in plan.scenarios and not state.marked("admin"):
                admin.populate(executor, actor, plan.parameters["admin"])
                state.mark("admin")
            if "property" in plan.parameters:
                p = plan.parameters["property"]
                for index in range(p["companies"]):
                    key = f"company/{index}"
                    if state.get(key) is None:
                        company = property_scenario.provision(executor, actor, index, p)
                        state.put(key, asdict(company))
                # Release read transactions before dispatching independent company workers.
                db.rollback()

                def company_at(index: int) -> Company:
                    value = state.get(f"company/{index}")
                    if value is None:
                        raise SeedError("缺少公司上下文")
                    return Company(**value)

                def populate(index: int) -> None:
                    key = f"housing/{index}"
                    if state.marked(key) or stop.is_set():
                        return
                    company = company_at(index)
                    account = state.account("property_admin", company.login)
                    resident_actor = Actor(
                        "property_admin", company.login, account["密码"], state.run_id
                    )
                    try:
                        with factory() as housing_db:
                            worker = Executor(state, housing_db, store, stop, progress.tick)
                            on_house: Callable[[str, str, str, int], None] | None = None
                            if "billing" in plan.parameters:
                                parameters = BillingParameters(**plan.parameters["billing"])
                                clock = state.get("billing_clock")
                                if clock is None:
                                    raise SeedError("缺少账单批次业务日期")
                                today = date.fromisoformat(clock["today"])
                                h = plan.parameters["housing"]
                                per_company = (
                                    len(company.communities)
                                    * h["buildings_per_community"]
                                    * (
                                        h["houses_per_building"]
                                        + h["units_per_building"] * h["houses_per_unit"]
                                    )
                                )

                                def bill_house(
                                    house_key: str, community: str, house: str, number: int
                                ) -> None:
                                    billing.populate_house(
                                        worker,
                                        resident_actor,
                                        company.id,
                                        community,
                                        house,
                                        house_key,
                                        company.index * per_company + number,
                                        parameters,
                                        today,
                                    )

                                on_house = bill_house

                            housing.populate(
                                worker,
                                resident_actor,
                                company,
                                plan.parameters["housing"],
                                on_house=on_house,
                            )
                        state.mark(key)
                    except BaseException:
                        stop.set()
                        raise
                    finally:
                        resident_actor.close(store)

                if "housing" in plan.parameters:
                    if plan.workers == 1:
                        for index in range(p["companies"]):
                            populate(index)
                    else:
                        with ThreadPoolExecutor(max_workers=plan.workers) as pool:
                            try:
                                for _ in pool.map(
                                    populate, range(p["companies"]), buffersize=plan.workers
                                ):
                                    pass
                            except BaseException:
                                stop.set()
                                raise
                for index in range(p["companies"]):
                    property_scenario.finalize(executor, actor, company_at(index), p["companies"])
            state.mark("complete")
        finally:
            actor.close(store)
    return report(state, plan, progress, factory)


def report(
    state: State, plan: Plan, progress: Progress, factory: sessionmaker[Session]
) -> dict[str, Any]:
    counts: dict[str, int] = {}
    bootstrap_id: str | None = None
    conditions: dict[str, set[str]] = {}
    for model, identifier, expected in state.entities():
        table = MODELS[model].__tablename__
        if model == "account" and expected.get("login_name", "").startswith("seed_root_"):
            bootstrap_id = identifier
        if model == "node":
            conditions.setdefault(table, set()).add(expected["node_type"])
        counts[table] = counts.get(table, 0) + 1
        if "enabled" in expected:
            conditions.setdefault(table, set()).add(
                "enabled" if expected["enabled"] else "disabled"
            )
        if "must_change_password" in expected:
            conditions.setdefault(table, set()).add(
                "password_change_required" if expected["must_change_password"] else "password_ready"
            )
    with factory() as db:
        prefix = "seed_" + state.run_id + "_"
        accounts = select(AdminAccount.id).where(
            or_(
                AdminAccount.login_name.startswith(prefix, autoescape=True),
                AdminAccount.id == bootstrap_id,
            )
        )
        counts["admin_account_roles"] = int(
            db.scalar(
                select(func.count())
                .select_from(AdminAccountRole)
                .where(AdminAccountRole.account_id.in_(accounts))
            )
            or 0
        )
        counts["admin_role_permissions"] = int(
            db.scalar(
                select(func.count())
                .select_from(AdminRolePermission)
                .join(AdminRole, AdminRole.id == AdminRolePermission.role_id)
                .where(AdminRole.code.startswith(prefix, autoescape=True))
            )
            or 0
        )
        system_roles = int(
            db.scalar(
                select(func.count())
                .select_from(AdminRole)
                .join(PropertyCompany, PropertyCompany.id == AdminRole.property_company_id)
                .where(PropertyCompany.code.startswith(prefix.upper(), autoescape=True))
            )
            or 0
        )
        counts["admin_roles"] = (
            counts.get("admin_roles", 0) + system_roles + int(bootstrap_id is not None)
        )
        counts["admin_audit_logs"] = int(
            db.scalar(
                select(func.count())
                .select_from(AdminAuditLog)
                .where(
                    or_(
                        AdminAuditLog.request_id.startswith(
                            "seed:" + state.run_id + ":", autoescape=True
                        ),
                        AdminAuditLog.request_id.startswith(
                            "seed_" + state.run_id + "_", autoescape=True
                        ),
                        (AdminAuditLog.action == "account.initialize")
                        & (AdminAuditLog.target_id == bootstrap_id)
                        if bootstrap_id
                        else false(),
                    )
                )
            )
            or 0
        )
    declared = set().union(*(entry.tables for entry in REGISTRY.values()))
    missing_states = {
        table: sorted({"enabled", "disabled"} - values)
        for table, values in conditions.items()
        if {"enabled", "disabled"} - values
    }
    result: dict[str, Any] = {
        "run_id": state.run_id,
        "scenarios": plan.scenarios,
        "expected": plan.counts(),
        "tables": counts,
        "unpopulated_tables": sorted(
            declared - {table for table, count in counts.items() if count}
        ),
        "missing_enable_states": missing_states,
        "states": {key: sorted(value) for key, value in conditions.items()},
        "steps": state.count(),
        "steps_this_execution": progress.completed,
        "elapsed_seconds": round(time.monotonic() - progress.started, 3),
    }
    if "billing" in plan.parameters:
        from devtools.seed.billing_report import billing_report

        clock = state.get("billing_clock")
        if clock is None:
            raise SeedError("缺少账单批次业务日期")
        with factory() as db:
            result["billing"] = billing_report(db, state, plan, date.fromisoformat(clock["today"]))
        counts.update(result["billing"]["tables"])
        result["unpopulated_tables"] = sorted(
            declared - {table for table, count in counts.items() if count}
        )
    return result


def run(
    *,
    plan: Plan | None,
    resume: str | None,
    root: Path,
    backend_root: Path,
    factory: sessionmaker[Session],
    client: Redis[str],
    settings: Settings,
    seed: SeedSettings,
) -> Path:
    guard(settings, seed)
    store = AdminSessionStore(client, settings, key_prefix=REDIS_KEY_PREFIX)
    engine = factory.kw["bind"]
    fingerprint = database_fingerprint(engine, backend_root)
    coverage(engine)
    store.client.ping()
    private_directory(root)
    if resume:
        directory = run_directory(root, resume)
        if not directory.is_dir() or directory.is_symlink():
            raise SeedError("批次不存在或目录无效")
    else:
        if plan is None:
            raise SeedError("缺少执行计划")
        validate_plan(plan)
        directory = run_directory(root, secrets.token_hex(12))
        private_directory(directory)
    print(f"批次：{directory.name}\n上下文：{directory}", flush=True)
    with file_lock(directory / "run.lock"):
        metadata_path = directory / "state.json"
        if resume:
            metadata = json.loads(metadata_path.read_text())
            if metadata["format_version"] != FORMAT_VERSION or metadata["database"] != fingerprint:
                raise SeedError("上下文版本或目标数据库不匹配")
            plan = Plan.model_validate(metadata["plan"])
            validate_plan(plan)
        else:
            assert plan is not None
            metadata = {
                "format_version": FORMAT_VERSION,
                "database": fingerprint,
                "plan": plan.model_dump(),
                "status": "pending",
            }
            if "billing" in plan.parameters:
                metadata["business_date"] = business_today().isoformat()
            save_json(metadata_path, metadata)
        assert plan is not None
        initializing = metadata["status"] == "pending"
        state = State(
            directory,
            create=not resume or (initializing and not (directory / "context.sqlite3").exists()),
            initialize=initializing,
        )
        try:
            identity = {
                "database": fingerprint,
                "plan": plan.model_dump(),
                "format_version": FORMAT_VERSION,
            }
            saved_identity = state.get("identity")
            if saved_identity is None:
                if not initializing:
                    raise SeedError("缺少批次身份记录，不能续跑")
                state.put("identity", identity)
            elif saved_identity != identity:
                raise SeedError("批次参数或数据库身份被修改，不能续跑")
            if "billing" in plan.parameters:
                clock = {"today": metadata.get("business_date")}
                if clock["today"] is None:
                    raise SeedError("缺少账单批次业务日期")
                saved_clock = state.get("billing_clock")
                if saved_clock is None and initializing:
                    state.put("billing_clock", clock)
                elif saved_clock != clock:
                    raise SeedError("账单批次业务日期被修改，不能续跑")
            metadata["status"] = "running"
            save_json(metadata_path, metadata)
            result = execute(state, plan, factory, store, seed, root, fingerprint)
            metadata["status"] = "complete"
            save_json(directory / "report.json", result)
            print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
        except BaseException:
            metadata["status"] = "interrupted"
            raise
        finally:
            try:
                state.export()
                save_json(metadata_path, metadata)
                print(f"账号清单：{directory / 'accounts.md'}", flush=True)
            finally:
                state.close()
    return directory
