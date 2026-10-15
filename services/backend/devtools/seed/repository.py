from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, inspect, select, text
from sqlalchemy.orm import Session

from backend_app.core.admin_security import verify_password
from backend_app.db.base import Base
from backend_app.models.admin import (
    AdminAccount,
    AdminAccountRole,
    AdminAuditLog,
    AdminRole,
    AdminRolePermission,
)
from backend_app.models.housing import House, HouseOwner, SpaceNode
from backend_app.models.property import Community, PropertyCompany
from devtools.seed.config import EXCLUDED_TABLES, REGISTRY, SeedError

MODELS: dict[str, type[Base]] = {
    "account": AdminAccount,
    "role": AdminRole,
    "company": PropertyCompany,
    "community": Community,
    "node": SpaceNode,
    "house": House,
    "owner": HouseOwner,
}


def coverage(engine: Engine) -> dict[str, list[str]]:
    actual = set(inspect(engine).get_table_names()) - EXCLUDED_TABLES.keys()
    mapped = set(Base.metadata.tables) - EXCLUDED_TABLES.keys()
    declared = set().union(*(scenario.tables for scenario in REGISTRY.values()))
    problems = {
        "uncovered": sorted(actual - declared),
        "unmapped": sorted(actual - mapped),
        "missing": sorted((mapped | declared) - actual),
    }
    if any(problems.values()):
        raise SeedError("数据表覆盖不完整：" + json.dumps(problems, ensure_ascii=False))
    return {
        table: [name for name, scenario in REGISTRY.items() if table in scenario.tables]
        for table in sorted(actual)
    }


def database_fingerprint(engine: Engine, backend_root: Path) -> str:
    config = Config(str(backend_root / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    with engine.connect() as connection:
        revisions = set(MigrationContext.configure(connection).get_current_heads())
        if revisions != set(scripts.get_heads()):
            raise SeedError("数据库迁移未到当前 head，请先执行 make migrate")
        identity = connection.execute(
            text("SELECT current_database(), oid FROM pg_database WHERE datname=current_database()")
        ).one()
    url = engine.url
    target = [url.host, url.port, identity[0], identity[1], sorted(revisions)]
    return hashlib.sha256(json.dumps(target).encode()).hexdigest()


class SeedRepository:
    """Read-only recovery and validation queries, isolated from production code."""

    def __init__(self, db: Session):
        self.db = db

    def account(self, scope: str, login: str) -> AdminAccount | None:
        return self.db.scalar(
            select(AdminAccount)
            .where(
                AdminAccount.scope == scope,
                AdminAccount.login_name == login,
            )
            .execution_options(populate_existing=True)
        )

    def has_platform_account(self) -> bool:
        return bool(
            self.db.scalar(
                select(
                    select(AdminAccount.id)
                    .where(
                        AdminAccount.scope == "platform_admin",
                    )
                    .exists()
                )
            )
        )

    def find(self, model: str, values: dict[str, Any]) -> Base | None:
        cls = MODELS[model]
        return self.db.scalar(
            select(cls)
            .where(*(getattr(cls, key) == value for key, value in values.items()))
            .execution_options(populate_existing=True)
        )

    def verify(self, model: str, identifier: str, expected: dict[str, Any]) -> None:
        record = self.db.get(MODELS[model], identifier, populate_existing=True)
        if record is None:
            raise SeedError(f"批次实体缺失：{model}/{identifier}")
        for key, value in expected.items():
            if key == "$password":
                if not isinstance(record, AdminAccount):
                    raise SeedError("密码校验目标不是账号")
                matches = verify_password(record.password_hash, value)
            elif key == "$roles":
                matches = set(
                    self.db.scalars(
                        select(AdminAccountRole.role_id).where(
                            AdminAccountRole.account_id == identifier
                        )
                    )
                ) == set(value)
            elif key == "$permissions":
                matches = set(
                    self.db.scalars(
                        select(AdminRolePermission.permission).where(
                            AdminRolePermission.role_id == identifier
                        )
                    )
                ) == set(value)
            elif key == "$super_admin":
                matches = (
                    bool(
                        self.db.scalar(
                            select(AdminRole.id)
                            .join(AdminAccountRole, AdminAccountRole.role_id == AdminRole.id)
                            .where(
                                AdminAccountRole.account_id == identifier,
                                AdminRole.is_system.is_(True),
                                AdminRole.enabled.is_(True),
                                AdminRole.code == "super_admin",
                            )
                        )
                    )
                    == value
                )
            else:
                matches = getattr(record, key) == value
            if not matches:
                raise SeedError(f"批次数据发生外部变化：{model}/{identifier}，字段 {key}")

    def recover(self, spec: dict[str, Any], request_id: str) -> str | None:
        audits = list(
            self.db.scalars(
                select(AdminAuditLog).where(
                    AdminAuditLog.scope == spec["scope"],
                    AdminAuditLog.request_id == request_id,
                    AdminAuditLog.action == spec["action"],
                    AdminAuditLog.result == "success",
                )
            )
        )
        if len(audits) > 1:
            raise SeedError("同一步骤出现多条成功记录，停止自动恢复")
        if audits:
            identifier = audits[0].target_id
            if not identifier:
                raise SeedError("步骤审计缺少目标实体")
            if spec.get("id") and spec["id"] != identifier:
                raise SeedError("步骤审计与目标实体不一致")
            return identifier
        if spec.get("unique") and self.find(spec["model"], spec["unique"]) is not None:
            raise SeedError("业务唯一键已存在但缺少本步骤审计，停止自动恢复")
        return None
