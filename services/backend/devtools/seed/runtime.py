from __future__ import annotations

import hashlib
import secrets
import threading
import time
from collections.abc import Callable
from typing import Any, cast

from sqlalchemy.orm import Session

from backend_app.core.admin_sessions import AdminSessionStore
from backend_app.core.errors import AppError
from backend_app.domain.admin.types import AdminScope
from backend_app.schemas import admin as a
from backend_app.schemas import housing as h
from backend_app.schemas import property as p
from backend_app.services.contracts.admin import AdminContext
from backend_app.services.platform_admin.admin import PlatformAdminService
from backend_app.services.platform_admin.property import PropertyOnboardingService
from backend_app.services.property_admin.admin import PropertyAdminService
from backend_app.services.property_admin.housing import PropertyHousingService
from devtools.seed.config import SeedError
from devtools.seed.repository import SeedRepository
from devtools.seed.state import State


def password() -> str:
    return secrets.token_urlsafe(24)


class Actor:
    def __init__(self, scope: AdminScope, login: str, secret: str, run_id: str):
        self.run_id = run_id
        self.scope = scope
        self.login = login
        self.secret = secret
        self.token: str | None = None
        self.context: AdminContext | None = None
        self.checked = 0.0
        self.auth_service: PlatformAdminService | PropertyAdminService | None = None

    def service(self, db: Session) -> PlatformAdminService | PropertyAdminService:
        if self.auth_service is None:
            self.auth_service = (
                PlatformAdminService(db)
                if self.scope == "platform_admin"
                else PropertyAdminService(db)
            )
        return self.auth_service

    def get(self, db: Session, store: AdminSessionStore) -> AdminContext:
        if self.context and time.monotonic() - self.checked < 30:
            return self.context
        service = self.service(db)
        if self.token:
            try:
                self.context = service.authenticate(store, self.token)
                self.checked = time.monotonic()
                return self.context
            except AppError:
                db.rollback()
                store.delete(self.scope, self.token)
                self.token = None
        # The CLI has no remote IP. A stable per-identity source retains account/source limits.
        self.token, _ = service.login(
            a.AdminLogin(login_name=self.login, password=self.secret),
            store,
            "seed-cli:" + self.login,
            "seed:" + self.run_id + ":auth:" + secrets.token_hex(4),
        )
        self.context = service.authenticate(store, self.token)
        self.checked = time.monotonic()
        return self.context

    def close(self, store: AdminSessionStore) -> None:
        if self.token:
            store.delete(self.scope, self.token)
            self.token = None


def invoke(
    db: Session,
    store: AdminSessionStore,
    actor: Actor,
    action: str,
    data: dict[str, Any],
    request_id: str,
) -> str:
    context = actor.get(db, store)
    platform = PlatformAdminService(db)
    onboarding = PropertyOnboardingService(db)
    housing = PropertyHousingService(db)
    values = data["values"]
    identifier = data.get("id", "")
    match action:
        case "role.create":
            return platform.create_role(context, a.RoleCreate(**values), request_id).id
        case "role.assign_permissions":
            platform.set_role_permissions(
                context, identifier, a.PermissionSet(**values), request_id
            )
        case "role.update":
            platform.update_role(context, identifier, a.RoleUpdate(**values), request_id)
        case "account.create":
            return platform.create_account(context, a.AccountCreate(**values), request_id).id
        case "account.update":
            platform.update_account(context, identifier, a.AccountUpdate(**values), request_id)
        case "account.password_change":
            actor.service(db).change_password(context, a.PasswordChange(**values), request_id)
        case "property.company.create":
            return onboarding.create_company(context, p.CompanyCreate(**values), request_id).id
        case "property.company.update":
            onboarding.update_company(context, identifier, p.CompanyUpdate(**values), request_id)
        case "property.community.create":
            return onboarding.create_community(context, p.CommunityCreate(**values), request_id).id
        case "property.community.update":
            onboarding.update_community(
                context, identifier, p.CommunityUpdate(**values), request_id
            )
        case "property.admin.create":
            return onboarding.create_admin(
                context, data["company_id"], p.PropertyAdminCreate(**values), request_id
            ).id
        case "property.admin.update":
            onboarding.update_admin(
                context, data["company_id"], identifier, a.AccountUpdate(**values), request_id
            )
        case "property.space.create":
            return housing.create_node(
                context, data["community_id"], h.SpaceNodeCreate(**values), request_id
            ).id
        case "property.space.update":
            housing.update_node(
                context, data["community_id"], identifier, h.SpaceNodeUpdate(**values), request_id
            )
        case "property.house.create":
            return housing.create_house(
                context, data["community_id"], h.HouseCreate(**values), request_id
            ).id
        case "property.house.update":
            housing.update_house(
                context, data["community_id"], identifier, h.HouseUpdate(**values), request_id
            )
        case "property.house_owner.create":
            return housing.create_owner(
                context,
                data["community_id"],
                data["house_id"],
                h.HouseOwnerCreate(**values),
                request_id,
            ).id
        case "property.house_owner.update":
            housing.update_owner(
                context,
                data["community_id"],
                data["house_id"],
                identifier,
                h.HouseOwnerUpdate(**values),
                request_id,
            )
        case _:
            raise SeedError("未注册的业务步骤")
    return cast(str, identifier)


class Executor:
    def __init__(
        self,
        state: State,
        db: Session,
        store: AdminSessionStore,
        stop: threading.Event | None = None,
        progress: Callable[[], None] | None = None,
    ):
        self.state = state
        self.db = db
        self.store = store
        self.repo = SeedRepository(db)
        self.stop = stop or threading.Event()
        self.progress = progress or (lambda: None)

    def request_id(self, key: str) -> str:
        return "seed:" + self.state.run_id + ":" + hashlib.sha256(key.encode()).hexdigest()[:24]

    def confirm(self, key: str, spec: dict[str, Any], data: dict[str, Any], identifier: str) -> str:
        result = {"model": spec["model"], "id": identifier, "expected": data["expected"]}
        self.state.complete(key, result, data.get("account"))
        self.progress()
        return identifier

    def step(
        self,
        key: str,
        actor: Actor,
        action: str,
        model: str,
        values: dict[str, Any],
        *,
        identifier: str | None = None,
        unique: dict[str, Any] | None = None,
        expected: dict[str, Any] | None = None,
        refs: dict[str, str] | None = None,
        factory: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    ) -> str:
        if self.stop.is_set():
            raise SeedError("批次停止，未开始的步骤保留待续跑")
        spec = {
            "action": action,
            "model": model,
            "scope": actor.scope,
            "id": identifier,
            "unique": unique or {},
            "values": values,
            "expected": expected or {},
            "refs": refs or {},
        }

        def prepare() -> dict[str, Any]:
            data = {
                "input": {"values": dict(values), "id": identifier, **(refs or {})},
                "expected": dict(expected or {}),
            }
            return factory(data) if factory else data

        data, result, existed = self.state.prepare(key, spec, prepare)
        if result is not None:
            return cast(str, result["id"])
        request_id = self.request_id(key)
        if existed:
            recovered = self.repo.recover(spec, request_id)
            if recovered:
                self.repo.verify(model, recovered, data["expected"])
                return self.confirm(key, spec, data, recovered)
        identifier = invoke(self.db, self.store, actor, action, data["input"], request_id)
        return self.confirm(key, spec, data, identifier)

    def create_account(
        self,
        key: str,
        actor: Actor,
        login: str,
        display: str,
        scenario: str,
        *,
        company_id: str | None = None,
        company_name: str = "",
        roles: list[str] | None = None,
    ) -> str:
        scope = "property_admin" if company_id else "platform_admin"
        values: dict[str, Any] = {"login_name": login, "display_name": display}
        if company_id is None:
            values["role_ids"] = roles or []

        def prepare(data: dict[str, Any]) -> dict[str, Any]:
            secret = password()
            data["input"]["values"]["password"] = secret
            data["expected"]["$password"] = secret
            data["account"] = {
                "所属批次": self.state.run_id,
                "场景": scenario,
                "登录端": scope,
                "登录名": login,
                "显示名称": display,
                "密码": secret,
                "所属物业公司": company_name,
            }
            return data

        expected: dict[str, Any] = {
            "login_name": login,
            "scope": scope,
            "property_company_id": company_id,
            "display_name": display,
            "enabled": True,
            "must_change_password": True,
        }
        if company_id is None:
            expected["$roles"] = roles or []
        else:
            expected["$super_admin"] = True
        return self.step(
            key,
            actor,
            "property.admin.create" if company_id else "account.create",
            "account",
            values,
            unique={"scope": scope, "login_name": login},
            expected=expected,
            refs={"company_id": company_id} if company_id else {},
            factory=prepare,
        )

    def change_password(self, key: str, account_id: str, scope: AdminScope, login: str) -> None:
        account = self.state.account(scope, login)
        actor = Actor(scope, login, account["密码"], self.state.run_id)

        def prepare(data: dict[str, Any]) -> dict[str, Any]:
            new_password = password()
            data["input"]["values"] = {
                "current_password": account["密码"],
                "new_password": new_password,
            }
            data["expected"]["$password"] = new_password
            data["account"] = {**account, "密码": new_password}
            return data

        try:
            self.step(
                key,
                actor,
                "account.password_change",
                "account",
                {},
                identifier=account_id,
                expected={"must_change_password": False},
                factory=prepare,
            )
        finally:
            actor.close(self.store)
