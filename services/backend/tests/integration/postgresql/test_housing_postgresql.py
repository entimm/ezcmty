from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from time import monotonic

import pytest
from pytest import MonkeyPatch
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, sessionmaker
from tests.support.housing_services import provision_housing

from backend_app.core.admin_sessions import AdminSessionStore
from backend_app.core.errors import AppError
from backend_app.models.housing import House, SpaceNode
from backend_app.models.property import Community
from backend_app.repositories.property import PropertyRepository
from backend_app.schemas import admin as admin_schema
from backend_app.schemas import housing as schema
from backend_app.schemas import property as property_schema
from backend_app.services.platform_admin.admin import PlatformAdminService
from backend_app.services.platform_admin.property import PropertyOnboardingService
from backend_app.services.property_admin.admin import PropertyAdminService
from backend_app.services.property_admin.housing import PropertyHousingService


@pytest.mark.parametrize("resource", ["root", "house", "owner"])
def test_concurrent_duplicate_creation_has_one_winner(
    real_admin: tuple[sessionmaker[Session], AdminSessionStore], resource: str
) -> None:
    factory, store = real_admin
    setup = provision_housing(factory, store)
    with factory() as db:
        house = PropertyHousingService(db).create_house(
            setup.context,
            setup.community_id,
            schema.HouseCreate(space_node_id=setup.node_id, room_no="101"),
            "house",
        )
    barrier = Barrier(2)

    def create() -> str:
        with factory() as db:
            context = PropertyAdminService(db).authenticate(store, setup.token)
            barrier.wait(timeout=10)
            service = PropertyHousingService(db)
            try:
                if resource == "root":
                    service.create_node(
                        context,
                        setup.community_id,
                        schema.SpaceNodeCreate(node_type="building", name="并发"),
                        "race",
                    )
                elif resource == "house":
                    service.create_house(
                        context,
                        setup.community_id,
                        schema.HouseCreate(space_node_id=setup.node_id, room_no="102"),
                        "race",
                    )
                else:
                    service.create_owner(
                        context,
                        setup.community_id,
                        house.id,
                        schema.HouseOwnerCreate(name="业主", phone="+8613800000000"),
                        "race",
                    )
            except AppError as exc:
                # The service must leave the transaction usable after a known conflict.
                assert db.scalar(select(func.count()).select_from(Community)) == 1
                return exc.code
            return "created"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: create(), range(2)))
    error = {
        "root": "property.duplicate_space_name",
        "house": "property.duplicate_room_no",
        "owner": "property.duplicate_house_owner",
    }[resource]
    assert sorted(results) == sorted(["created", error])


@pytest.mark.parametrize("ancestor", ["community", "node"])
def test_create_rechecks_disabled_parent_after_waiting_for_lock(
    real_admin: tuple[sessionmaker[Session], AdminSessionStore],
    monkeypatch: MonkeyPatch,
    ancestor: str,
) -> None:
    factory, store = real_admin
    setup = provision_housing(factory, store)
    observed = Event()
    original = PropertyRepository.community

    def community(
        repo: PropertyRepository,
        community_id: str,
        *,
        lock: bool = False,
        company_scope_id: str | None = None,
    ) -> Community | None:
        if lock:
            observed.set()
        return original(repo, community_id, lock=lock, company_scope_id=company_scope_id)

    monkeypatch.setattr(PropertyRepository, "community", community)

    def create() -> str:
        with factory() as db:
            try:
                PropertyHousingService(db).create_house(
                    setup.context,
                    setup.community_id,
                    schema.HouseCreate(space_node_id=setup.node_id, room_no="101"),
                    "racing-create",
                )
            except AppError as exc:
                return exc.code
            return "unexpected_success"

    with factory() as writer, ThreadPoolExecutor(max_workers=1) as pool:
        parent = PropertyRepository(writer).community(setup.community_id, lock=True)
        assert parent
        if ancestor == "community":
            parent.enabled = False
        else:
            node = writer.get(SpaceNode, setup.node_id)
            assert node
            node.enabled = False
        # Prove the competing request is actually blocked in PostgreSQL, without sleeps.
        pid = writer.scalar(text("SELECT pg_backend_pid()"))
        observed.clear()
        pending = pool.submit(create)
        assert observed.wait(10)
        with factory() as observer:
            deadline = monotonic() + 2
            while not observer.scalar(
                text(
                    "SELECT EXISTS (SELECT 1 FROM pg_stat_activity "
                    "WHERE :pid = ANY(pg_blocking_pids(pid)))"
                ),
                {"pid": pid},
            ):
                assert monotonic() < deadline, (
                    "The housing write never waited for the community lock"
                )
        writer.commit()
        assert pending.result(timeout=10) == "property.housing_disabled"
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(House)) == 0


@pytest.mark.parametrize("change", ["company", "account", "password"])
def test_housing_writer_rejects_revoked_authorization(
    real_admin: tuple[sessionmaker[Session], AdminSessionStore], change: str
) -> None:
    factory, store = real_admin
    setup = provision_housing(factory, store)
    with factory() as stale, factory() as changed:
        context = PropertyAdminService(stale).authenticate(store, setup.token)
        actor = PlatformAdminService(changed).authenticate(store, setup.platform_token)
        service = PropertyOnboardingService(changed)
        if change == "company":
            service.update_company(
                actor, setup.company_id, property_schema.CompanyUpdate(enabled=False), "disable"
            )
        elif change == "account":
            service.update_admin(
                actor,
                setup.company_id,
                context.account_id,
                admin_schema.AccountUpdate(enabled=False),
                "disable",
            )
        else:
            service.reset_admin_password(
                actor,
                setup.company_id,
                context.account_id,
                admin_schema.PasswordReset(password="changed-private-password"),
                "reset",
            )
        with pytest.raises(AppError) as caught:
            PropertyHousingService(stale).create_house(
                context,
                setup.community_id,
                schema.HouseCreate(space_node_id=setup.node_id, room_no="101"),
                "stale",
            )
        assert caught.value.code == "auth.unauthenticated"
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(House)) == 0
