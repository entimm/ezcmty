from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, select, text
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker
from tests.support.mysql import PASSWORD, platform_token
from tests.support.paths import BACKEND_ROOT

from backend_app.core.admin_sessions import AdminSessionStore
from backend_app.core.errors import AppError
from backend_app.core.identifiers import new_id
from backend_app.models.admin import AdminAccount, AdminAccountRole, AdminRole, utc_now
from backend_app.models.property import Community, PropertyCompany
from backend_app.schemas import admin as admin_schema
from backend_app.schemas import property as schema
from backend_app.services.platform_admin.admin import PlatformAdminService
from backend_app.services.platform_admin.property import PropertyOnboardingService
from backend_app.services.property_admin.admin import PropertyAdminService


def test_mysql_role_uniqueness_and_company_association_constraints(
    real_admin: tuple[sessionmaker[Session], AdminSessionStore],
) -> None:
    factory, _ = real_admin
    with factory() as db:
        first, second = (
            PropertyCompany(code="first", name="第一"),
            PropertyCompany(code="second", name="第二"),
        )
        db.add_all([first, second])
        db.flush()
        platform = AdminRole(scope="platform_admin", code="super_admin", name="平台")
        role1 = AdminRole(
            scope="property_admin", property_company_id=first.id, code="super_admin", name="第一"
        )
        role2 = AdminRole(
            scope="property_admin", property_company_id=second.id, code="super_admin", name="第二"
        )
        account = AdminAccount(
            scope="property_admin",
            property_company_id=first.id,
            login_name="member",
            display_name="成员",
            password_hash="test-hash",
        )
        platform_account = AdminAccount(
            scope="platform_admin",
            login_name="member",
            display_name="平台",
            password_hash="test-hash",
        )
        db.add_all([platform, role1, role2, account, platform_account])
        db.flush()
        db.add_all(
            [
                AdminAccountRole(
                    scope="property_admin",
                    property_company_id=first.id,
                    account_id=account.id,
                    role_id=role1.id,
                ),
                AdminAccountRole(
                    scope="platform_admin", account_id=platform_account.id, role_id=platform.id
                ),
                Community(
                    property_company_id=first.id, code="community", name="小区", address="地址"
                ),
            ]
        )
        db.commit()
        assert (
            platform.platform_code == "super_admin"
            and role1.platform_code is None
            and role2.platform_code is None
        )

        def reject(row: AdminRole | AdminAccount | AdminAccountRole) -> None:
            with pytest.raises(DBAPIError) as caught, db.begin_nested():
                db.add(row)
                db.flush()
            assert caught.value.orig is not None and caught.value.orig.args[0] in (1062, 1452, 3819)

        reject(AdminRole(scope="platform_admin", code="super_admin", name="重复平台角色"))
        reject(
            AdminRole(
                scope="property_admin",
                property_company_id=first.id,
                code="super_admin",
                name="重复公司角色",
            )
        )
        reject(
            AdminRole(scope="platform_admin", property_company_id=first.id, code="bad", name="非法")
        )
        reject(AdminRole(scope="property_admin", code="bad", name="缺少公司"))
        reject(
            AdminAccount(
                scope="property_admin",
                login_name="missing",
                display_name="缺少公司",
                password_hash="test-hash",
            )
        )
        reject(
            AdminAccount(
                scope="platform_admin",
                property_company_id=first.id,
                login_name="bad",
                display_name="非法",
                password_hash="test-hash",
            )
        )
        reject(
            AdminAccount(
                scope="property_admin",
                property_company_id=second.id,
                login_name="member",
                display_name="跨公司重名",
                password_hash="test-hash",
            )
        )
        reject(
            AdminAccountRole(
                scope="property_admin",
                property_company_id=first.id,
                account_id=account.id,
                role_id=role2.id,
            )
        )
        reject(
            AdminAccountRole(
                scope="property_admin",
                property_company_id=second.id,
                account_id=account.id,
                role_id=role2.id,
            )
        )
        reject(AdminAccountRole(scope="property_admin", account_id=account.id, role_id=role2.id))
        reject(
            AdminAccountRole(
                scope="property_admin",
                property_company_id=first.id,
                account_id=account.id,
                role_id=platform.id,
            )
        )
        for statement in (
            "UPDATE property_companies SET enabled=2 WHERE code='first'",
            "UPDATE communities SET enabled=2 WHERE code='community'",
            "DELETE FROM property_companies WHERE code='first'",
        ):
            with pytest.raises(DBAPIError) as caught, db.begin_nested():
                db.execute(text(statement))
            assert caught.value.orig is not None and caught.value.orig.args[0] in (1451, 3819)
        timestamp = inspect(db.connection()).get_columns("property_companies")[-1]["type"]
        assert isinstance(timestamp, DATETIME) and timestamp.fsp == 6


def test_concurrent_company_provisioning_and_last_admin_disables(
    real_admin: tuple[sessionmaker[Session], AdminSessionStore],
) -> None:
    factory, store = real_admin
    token = platform_token(factory, store)
    with factory() as db:
        actor = PlatformAdminService(db).authenticate(store, token)
        company = PropertyOnboardingService(db).create_company(
            actor, schema.CompanyCreate(code="concurrent", name="并发"), "create-company"
        )
    barrier = Barrier(2)

    def provision(name: str) -> str:
        with factory() as db:
            actor = PlatformAdminService(db).authenticate(store, token)
            barrier.wait(timeout=10)
            return (
                PropertyOnboardingService(db)
                .create_admin(
                    actor,
                    company.id,
                    schema.PropertyAdminCreate(
                        login_name=name, display_name=name, password=PASSWORD
                    ),
                    "provision",
                )
                .id
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(provision, ("first", "second")))
    with factory() as db:
        roles = list(
            db.scalars(select(AdminRole).where(AdminRole.property_company_id == company.id))
        )
        assert len(roles) == 1 and roles[0].is_system
        links = list(
            db.scalars(
                select(AdminAccountRole).where(AdminAccountRole.property_company_id == company.id)
            )
        )
        assert len(links) == 2 and {link.role_id for link in links} == {roles[0].id}
    barrier = Barrier(2)

    def disable(account_id: str) -> str:
        with factory() as db:
            actor = PlatformAdminService(db).authenticate(store, token)
            barrier.wait(timeout=10)
            try:
                PropertyOnboardingService(db).update_admin(
                    actor,
                    company.id,
                    account_id,
                    admin_schema.AccountUpdate(enabled=False),
                    "disable",
                )
                return "success"
            except AppError as error:
                db.rollback()
                return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(disable, ids))
    assert sorted(results) == ["admin.last_super_admin", "success"]
    with factory() as db:
        accounts = list(
            db.scalars(select(AdminAccount).where(AdminAccount.property_company_id == company.id))
        )
        assert sum(account.enabled for account in accounts) == 1


def test_mysql_property_session_revocation_and_same_company_authorization(
    real_admin: tuple[sessionmaker[Session], AdminSessionStore],
) -> None:
    factory, store = real_admin
    platform = platform_token(factory, store)
    with factory() as db:
        actor = PlatformAdminService(db).authenticate(store, platform)
        service = PropertyOnboardingService(db)
        company = service.create_company(
            actor, schema.CompanyCreate(code="sessions", name="会话"), "create-company"
        )
        first = service.create_admin(
            actor,
            company.id,
            schema.PropertyAdminCreate(login_name="first", display_name="第一", password=PASSWORD),
            "first",
        )
        second = service.create_admin(
            actor,
            company.id,
            schema.PropertyAdminCreate(login_name="second", display_name="第二", password=PASSWORD),
            "second",
        )
        service.update_company(actor, company.id, schema.CompanyUpdate(enabled=True), "enable")
        for identifier in (first.id, second.id):
            account = db.get(AdminAccount, identifier)
            assert account
            account.must_change_password = False
        db.commit()
        prop = PropertyAdminService(db)
        token, _ = prop.login(
            admin_schema.AdminLogin(login_name="first", password=PASSWORD), store, "ip", "login"
        )
        context = prop.authenticate(store, token)
        assert context.property_company_id == company.id
        service.update_company(
            actor, company.id, schema.CompanyUpdate(enabled=False), "disable-company"
        )
        service.update_company(actor, company.id, schema.CompanyUpdate(enabled=True), "reenable")
        with pytest.raises(AppError) as caught:
            PropertyAdminService(db).authenticate(store, token)
        assert caught.value.code == "auth.unauthenticated" and store.read("property_admin", token)
        prop = PropertyAdminService(db)
        token, _ = prop.login(
            admin_schema.AdminLogin(login_name="first", password=PASSWORD),
            store,
            "ip",
            "login-again",
        )
        context = prop.authenticate(store, token)
        # Platform provisioning mutations retain their actor and target company.
        service.update_admin(
            actor,
            company.id,
            second.id,
            admin_schema.AccountUpdate(enabled=False),
            "own-company-disable",
        )
        other = service.create_company(
            actor, schema.CompanyCreate(code="other", name="另一"), "other-company"
        )
        target = service.create_admin(
            actor,
            other.id,
            schema.PropertyAdminCreate(login_name="other", display_name="另一", password=PASSWORD),
            "other-admin",
        )
        with pytest.raises(AppError) as caught:
            service.update_admin(
                actor,
                company.id,
                target.id,
                admin_schema.AccountUpdate(enabled=False),
                "cross-company",
            )
        assert caught.value.code == "resource.not_found"
        assert prop.identity.repo.account(second.id) is not None
        assert prop.identity.repo.account(target.id) is None


def test_mysql_migration_roundtrip_and_unmapped_identity_preflight(
    real_admin: tuple[sessionmaker[Session], AdminSessionStore],
) -> None:
    factory, store = real_admin
    platform_token(factory, store)
    cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
    command.downgrade(cfg, "20261014_admin_foundation")
    identifier = new_id()
    with factory() as db:
        assert "property_companies" not in inspect(db.connection()).get_table_names()
        db.execute(
            text(
                "INSERT INTO admin_accounts (id,scope,login_name,display_name,password_hash,"
                "enabled,must_change_password,session_version,created_at) "
                "VALUES (UUID_TO_BIN(:id),'property_admin','unmapped','Unmapped',"
                "'test-hash',1,1,1,:time)"
            ),
            {"id": identifier, "time": utc_now()},
        )
        db.commit()
    with pytest.raises(RuntimeError, match="company mapping"):
        command.upgrade(cfg, "head")
    with factory() as db:
        assert "property_companies" not in inspect(db.connection()).get_table_names()
        assert (
            db.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            == "20261014_admin_foundation"
        )
        db.execute(text("DELETE FROM admin_accounts WHERE scope='property_admin'"))
        db.commit()
    command.upgrade(cfg, "head")
    with factory() as db:
        root = db.scalar(select(AdminAccount).where(AdminAccount.login_name == "root"))
        assert root and root.property_company_id is None
        company = PropertyCompany(code="keep", name="保留")
        db.add(company)
        db.commit()
    with pytest.raises(RuntimeError, match="organization data"):
        command.downgrade(cfg, "20261014_admin_foundation")
    with factory() as db:
        assert db.scalar(select(PropertyCompany).where(PropertyCompany.code == "keep")) is not None
