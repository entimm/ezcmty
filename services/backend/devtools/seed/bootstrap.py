from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from backend_app.core.admin_security import verify_password
from backend_app.services.platform_admin.admin import PlatformAdminService
from devtools.seed.config import SeedError
from devtools.seed.runtime import Actor, Executor, password
from devtools.seed.state import file_lock, save_json


class SeedSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SEED_", env_file=".env", extra="ignore", hide_input_in_errors=True
    )
    enabled: bool = False
    login_name: str | None = None
    password: SecretStr | None = None


def platform_actor(
    executor: Executor, root: Path, fingerprint: str, settings: SeedSettings
) -> Actor:
    if settings.login_name or settings.password:
        if not settings.login_name or not settings.password:
            raise SeedError("SEED_LOGIN_NAME 和 SEED_PASSWORD 必须同时提供")
        actor = Actor(
            "platform_admin",
            settings.login_name,
            settings.password.get_secret_value(),
            executor.state.run_id,
        )
        actor.get(executor.db, executor.store)
        if actor.context and actor.context.must_change_password:
            actor.close(executor.store)
            raise SeedError("配置的执行账号须先完成首次改密")
        return actor
    path = root / f"operator-{fingerprint}.json"
    with file_lock(root / f"operator-{fingerprint}.lock"):
        if path.is_symlink():
            raise SeedError("执行账号凭据不能是符号链接")
        if path.exists():
            path.chmod(0o600)
            operator = json.loads(path.read_text())
        else:
            if executor.repo.has_platform_account():
                raise SeedError("已有平台账号，请配置 SEED_LOGIN_NAME 和 SEED_PASSWORD")
            operator = {
                "login": "seed_root_" + executor.state.run_id,
                "initial": password(),
                "password": password(),
                "run_id": executor.state.run_id,
            }
            save_json(path, operator)
        login = operator["login"]
        if operator["run_id"] == executor.state.run_id:
            spec = {
                "action": "account.initialize",
                "model": "account",
                "scope": "platform_admin",
                "request_id": "bootstrap",
                "unique": {"scope": "platform_admin", "login_name": login},
            }
            info = {
                "所属批次": executor.state.run_id,
                "场景": "bootstrap",
                "登录端": "platform_admin",
                "登录名": login,
                "显示名称": "开发填充管理员",
                "密码": operator["initial"],
                "所属物业公司": "",
            }
            data, result, _ = executor.state.prepare(
                "bootstrap",
                spec,
                lambda: {
                    "expected": {
                        "login_name": login,
                        "scope": "platform_admin",
                        "$password": operator["initial"],
                        "must_change_password": True,
                        "enabled": True,
                        "$super_admin": True,
                    },
                    "account": info,
                },
            )
            if result is None:
                account = executor.repo.account("platform_admin", login)
                if account is None:
                    PlatformAdminService(executor.db).initialize_super_admin(
                        login, info["显示名称"], operator["initial"]
                    )
                    account = executor.repo.account("platform_admin", login)
                if account is None:
                    raise SeedError("初始化账号未找到")
                executor.repo.verify("account", account.id, data["expected"])
                executor.confirm("bootstrap", spec, data, account.id)
        account = executor.repo.account("platform_admin", login)
        if account is None:
            raise SeedError("本地执行账号已不存在，请核对数据库与原批次")
        if verify_password(account.password_hash, operator["password"]):
            secret = operator["password"]
        elif verify_password(account.password_hash, operator["initial"]):
            secret = operator["initial"]
        else:
            raise SeedError("执行账号密码已变化，请提供有效的 SEED_LOGIN_NAME/SEED_PASSWORD")
        actor = Actor("platform_admin", login, secret, executor.state.run_id)
        if account.must_change_password:
            if operator["run_id"] != executor.state.run_id:
                raise SeedError("初始化尚未完成，请先续跑执行账号所属批次：" + operator["run_id"])

            def prepare(change: dict[str, Any]) -> dict[str, Any]:
                change["input"]["values"] = {
                    "current_password": operator["initial"],
                    "new_password": operator["password"],
                }
                change["expected"]["$password"] = operator["password"]
                change["account"] = {**info, "密码": operator["password"]}
                return change

            try:
                executor.step(
                    "bootstrap/password",
                    actor,
                    "account.password_change",
                    "account",
                    {},
                    identifier=account.id,
                    expected={"must_change_password": False},
                    factory=prepare,
                )
            finally:
                actor.close(executor.store)
            actor = Actor("platform_admin", login, operator["password"], executor.state.run_id)
        actor.get(executor.db, executor.store)
        return actor
