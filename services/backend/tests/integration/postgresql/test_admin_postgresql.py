from __future__ import annotations

from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect, select, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Session, sessionmaker
from tests.support.admin_services import PASSWORD

from backend_app.core.admin_sessions import AdminSessionStore
from backend_app.core.errors import AppError
from backend_app.db.base import Base
from backend_app.models.admin import AdminAccount, AdminAuditLog, AdminRole, AdminRolePermission
from backend_app.models.housing import House, HouseOwner, SpaceNode
from backend_app.models.property import Community, PropertyCompany
from backend_app.schemas import admin as schema
from backend_app.services.platform_admin.admin import PlatformAdminService


def test_competing_super_admin_disables_preserve_one_valid_admin(
    real_admin: tuple[sessionmaker[Session], AdminSessionStore],
) -> None:
    factory, store = real_admin
    with factory() as db:
        service = PlatformAdminService(db)
        service.initialize_super_admin("first", "First", PASSWORD)
        first = db.scalar(select(AdminAccount).where(AdminAccount.login_name == "first"))
        system = db.scalar(select(AdminRole).where(AdminRole.code == "super_admin"))
        assert first and system
        first.must_change_password = False
        db.commit()
        first_token, _ = store.create("platform_admin", first.id, first.session_version)
        context = service.authenticate(store, first_token)
        second = service.create_account(
            context,
            schema.AccountCreate(
                login_name="second", display_name="Second", password=PASSWORD, role_ids=[system.id]
            ),
            "create-second",
        )
        account = db.get(AdminAccount, second.id)
        assert account
        account.must_change_password = False
        db.commit()
        second_token, _ = store.create("platform_admin", account.id, account.session_version)
        first_id, second_id = first.id, account.id
    barrier = Barrier(2)

    def disable(token: str, target: str) -> str:
        with factory() as db:
            service = PlatformAdminService(db)
            context = service.authenticate(store, token)
            barrier.wait(timeout=10)
            try:
                service.update_account(
                    context, target, schema.AccountUpdate(enabled=False), "concurrent-disable"
                )
                return "success"
            except AppError as error:
                db.rollback()
                return error.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(disable, first_token, second_id),
            executor.submit(disable, second_token, first_id),
        ]
        results = [future.result(timeout=15) for future in futures]
    assert sorted(results) == ["auth.unauthenticated", "success"]
    with factory() as db:
        role = db.scalar(select(AdminRole).where(AdminRole.code == "super_admin"))
        assert role
        assert len(PlatformAdminService(db).repo.active_super_accounts(role.id)) == 1


def test_real_redis_revocation_and_scope_separation(
    real_admin: tuple[sessionmaker[Session], AdminSessionStore],
) -> None:
    factory, store = real_admin
    with factory() as db:
        service = PlatformAdminService(db)
        service.initialize_super_admin("admin", "Admin", PASSWORD)
        account = db.scalar(select(AdminAccount))
        assert account
        account.must_change_password = False
        db.commit()
        token, _ = store.create("platform_admin", account.id, account.session_version)
        assert store.read("property_admin", token) is None
        context = service.authenticate(store, token)
        service.change_password(
            context,
            schema.PasswordChange(current_password=PASSWORD, new_password="another-test-password"),
            "password-change",
        )
        assert store.read("platform_admin", token) is not None
    with factory() as db:
        with pytest.raises(AppError) as caught:
            PlatformAdminService(db).authenticate(store, token)
        assert caught.value.code == "auth.unauthenticated"
    # Real Lua counters enforce both account and source limits.
    source = uuid4().hex
    for _ in range(store.settings.admin_login_limit):
        store.limit_login("platform_admin", "limit-" + source, source)
    with pytest.raises(AppError) as caught:
        store.limit_login("platform_admin", "other-" + source, source)
    assert caught.value.code == "auth.rate_limited"


def test_native_types_and_fresh_migration_schema(
    real_admin: tuple[sessionmaker[Session], AdminSessionStore],
) -> None:
    factory, _ = real_admin
    legacy_id = str(uuid4())
    with factory() as db:
        service = PlatformAdminService(db)
        service.initialize_super_admin("admin", "Admin", PASSWORD)
        account = db.scalar(select(AdminAccount))
        assert account is not None and UUID(account.id).version == 7
        account_id = account.id
        company = PropertyCompany(code="UUID_COMPANY", name="UUID company")
        db.add(company)
        db.flush()
        community = Community(
            property_company_id=company.id,
            code="UUID_COMMUNITY",
            name="UUID community",
            address="Address",
        )
        db.add(community)
        db.flush()
        node = SpaceNode(community_id=community.id, node_type="building", name="A")
        db.add(node)
        db.flush()
        house = House(community_id=community.id, space_node_id=node.id, room_no="101")
        db.add(house)
        db.flush()
        db.add(HouseOwner(house_id=house.id, name="Owner", phone="13800000000"))
        role = AdminRole(scope="platform_admin", code="uuid_reader", name="Reader")
        db.add(role)
        db.add(
            AdminAccount(
                id=legacy_id,
                scope="platform_admin",
                login_name="legacy",
                display_name="Legacy",
                password_hash=account.password_hash,
            )
        )
        db.flush()
        db.add(
            AdminRolePermission(
                scope="platform_admin", role_id=role.id, permission="admin.account.read"
            )
        )
        db.add(
            AdminAuditLog(
                scope="platform_admin",
                actor_id=legacy_id,
                action="uuid.test",
                target_type="account",
                target_id=account_id,
                result="success",
                request_id="uuid-test",
            )
        )
        db.add(
            AdminAuditLog(
                scope="platform_admin",
                action="uuid.null-test",
                target_type="account",
                result="failure",
                request_id="uuid-null-test",
            )
        )
        db.commit()
        connection = db.connection()
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
        inspector = inspect(connection)
        uuid_columns = {
            "id",
            "account_id",
            "role_id",
            "actor_id",
            "target_id",
            "property_company_id",
            "community_id",
            "parent_id",
            "space_node_id",
            "house_id",
            "bill_id",
            "basis_version_id",
            "operation_id",
            "reverses_entry_id",
            "created_by",
            "voided_by",
        }
        for table in Base.metadata.sorted_tables:
            columns = {column["name"]: column for column in inspector.get_columns(table.name)}
            assert columns["created_at"]["nullable"] is False
            for column in columns.values():
                if column["name"].endswith("_at"):
                    timestamp = column["type"]
                    assert isinstance(timestamp, TIMESTAMP) and timestamp.timezone
                    assert timestamp.precision == 6
            if table.name == "admin_audit_logs":
                assert isinstance(columns["metadata"]["type"], JSONB)
            for name in uuid_columns & columns.keys():
                uuid_type = columns[name]["type"]
                assert isinstance(uuid_type, PGUUID)
            values: Sequence[datetime] = (
                connection.execute(text(f"SELECT created_at FROM {table.name}")).scalars().all()
            )
            if table.name not in {
                "bills",
                "property_fee_basis_versions",
                "bill_operations",
                "bill_settlement_entries",
            }:
                assert values
            assert all(value is not None for value in values)
        for identifier in (account_id, legacy_id):
            row = (
                connection.execute(
                    text(
                        "SELECT id, id::text AS text_id FROM admin_accounts "
                        "WHERE id = CAST(:identifier AS uuid)"
                    ),
                    {"identifier": identifier},
                )
                .mappings()
                .one()
            )
            assert row["id"] == UUID(identifier) and row["text_id"] == identifier
            entity = db.get(AdminAccount, identifier)
            assert entity is not None and entity.id == identifier
        references = connection.execute(
            text("SELECT actor_id, target_id FROM admin_audit_logs WHERE action = 'uuid.test'")
        ).one()
        assert references == (UUID(legacy_id), UUID(account_id))
        nullable = connection.execute(
            text("SELECT actor_id, target_id FROM admin_audit_logs WHERE action = 'uuid.null-test'")
        ).one()
        assert nullable == (None, None)
