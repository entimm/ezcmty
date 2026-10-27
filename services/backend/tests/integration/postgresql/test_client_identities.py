from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier, Event

import pytest
from sqlalchemy import event, func, insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from tests.support.client_identities import (
    SUBJECTS,
    TestIdentityProvider,
    TestIdentitySource,
    identity_registry,
)

from backend_app.core.admin_sessions import AdminSessionStore
from backend_app.core.errors import AppError
from backend_app.core.identifiers import new_id
from backend_app.domain.client.types import ClientAuthorization, ExtraIdentityAuthorization
from backend_app.models.admin import utc_now
from backend_app.models.miniapp import MiniappUser, MiniappUserIdentity
from backend_app.services.client.identities import ClientIdentityRegistry, ClientIdentityService


@pytest.fixture
def identity_data(
    real_admin: tuple[sessionmaker[Session], AdminSessionStore],
) -> tuple[sessionmaker[Session], ClientAuthorization, list[str]]:
    factory, _ = real_admin
    with factory() as db:
        SUBJECTS.create(db.connection())
        user = MiniappUser(wechat_openid="identity-owner")
        db.add(user)
        db.flush()
        ctx = ClientAuthorization(user.id, user.session_version)
        subjects = [new_id() for _ in range(4)]
        db.execute(
            insert(SUBJECTS),
            [
                {"id": value, "name": f"测试主体{index}", "enabled": index != 3}
                for index, value in enumerate(subjects)
            ],
        )
        db.commit()
    return factory, ctx, subjects


def test_resident_is_derived_without_links_and_uuid_is_never_a_resident_alias(
    identity_data: tuple[sessionmaker[Session], ClientAuthorization, list[str]],
) -> None:
    factory, ctx, _ = identity_data
    with factory() as db:
        service = ClientIdentityService(db)
        items, total = service.list(ctx, page=1, page_size=20)
        assert total == 1 and [item.id for item in items] == ["resident"]
        assert service.get(ctx, "resident") == items[0]
        assert service.authorize(ctx, "resident", expected_type="resident") == ctx
        assert service.list(ctx, page=2, page_size=1) == ([], 1)
        with pytest.raises(AppError) as caught:
            service.authorize(ctx, ctx.user_id, expected_type="resident")
        assert caught.value.code == "resource.not_found"
        assert db.scalar(select(func.count()).select_from(MiniappUserIdentity)) == 0


def test_directory_merges_multiple_types_subjects_before_counting_and_paging(
    identity_data: tuple[sessionmaker[Session], ClientAuthorization, list[str]],
) -> None:
    factory, ctx, subjects = identity_data
    with factory() as db:
        registry = identity_registry(db, "test_staff", "test_shop")
        service = ClientIdentityService(db, registry)
        ids = [service.grant(ctx, "test_staff", value).id for value in subjects[:2]]
        ids.append(service.grant(ctx, "test_shop", subjects[2]).id)
        unknown = MiniappUserIdentity(
            user_id=ctx.user_id, identity_type="not_registered", subject_id=subjects[0]
        )
        disabled = MiniappUserIdentity(
            user_id=ctx.user_id, identity_type="test_staff", subject_id=subjects[3]
        )
        db.add_all([unknown, disabled])
        db.commit()
        statements: list[str] = []

        def capture(*args: object) -> None:
            statements.append(str(args[2]))

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            first, total = service.list(ctx, page=1, page_size=2)
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)
        assert [item.id for item in first] == ["resident", ids[0]] and total == 4
        directory_sql = [sql for sql in statements if "identity_candidates AS" in sql]
        assert len(directory_sql) == 1
        assert "UNION ALL" in directory_sql[0] and "identity_total" in directory_sql[0]
        second, total = service.list(ctx, page=2, page_size=2)
        assert [item.id for item in second] == ids[1:] and total == 4
        assert service.list(ctx, page=3, page_size=2) == ([], 4)
        for index, identifier in enumerate(ids):
            expected = "test_staff" if index < 2 else "test_shop"
            auth = service.authorize(ctx, identifier, expected_type=expected)
            assert isinstance(auth, ExtraIdentityAuthorization)
            assert auth.subject_id == subjects[index]
        # The same root authorization alternates back to resident without mutable session state.
        assert service.authorize(ctx, "resident", expected_type="resident") == ctx
        with pytest.raises(AppError) as caught:
            service.authorize(ctx, ids[0], expected_type="resident")
        assert caught.value.code == "client.identity_mismatch"
        assert service.get(ctx, ids[0]).id == ids[0]


@pytest.mark.parametrize("kind", ["revoked", "unknown", "closed", "subject", "other_user"])
def test_extra_identity_failures_are_precise_and_do_not_revoke_root(
    identity_data: tuple[sessionmaker[Session], ClientAuthorization, list[str]], kind: str
) -> None:
    factory, ctx, subjects = identity_data
    with factory() as db:
        registry = identity_registry(db, "test_staff")
        service = ClientIdentityService(db, registry)
        item = service.grant(ctx, "test_staff", subjects[0])
        if kind == "revoked":
            service.revoke(ctx, item.id, expected_version=1)
        elif kind == "unknown":
            registry = ClientIdentityRegistry()
            service = ClientIdentityService(db, registry)
        elif kind == "closed":
            provider = registry.providers.get("test_staff")
            assert isinstance(provider, TestIdentityProvider)
            provider.enabled = False
        elif kind == "subject":
            db.execute(update(SUBJECTS).values(enabled=False))
        else:
            other = MiniappUser(wechat_openid="other")
            db.add(other)
            db.flush()
            ctx = ClientAuthorization(other.id, 1)
        db.commit()
        with pytest.raises(AppError) as caught:
            service.authorize(ctx, item.id, expected_type="resident")
        assert caught.value.code == (
            "resource.not_found" if kind == "other_user" else "client.identity_unavailable"
        )
        assert service.authorize(ctx, "resident", expected_type="resident") == ctx
        remaining, total = service.list(ctx, page=1, page_size=20)
        assert total == 1 and [value.id for value in remaining] == ["resident"]


def test_dependency_failures_propagate_in_directory_and_details(
    identity_data: tuple[sessionmaker[Session], ClientAuthorization, list[str]],
) -> None:
    factory, ctx, subjects = identity_data
    with factory() as db:
        provider = TestIdentityProvider(db, "test_staff")
        source = TestIdentitySource()
        registry = ClientIdentityRegistry()
        registry.register(provider, source)
        service = ClientIdentityService(db, registry)
        item = service.grant(ctx, "test_staff", subjects[0])
        provider.failed = source.failed = True
        for call in (
            lambda: service.list(ctx, page=1, page_size=20),
            lambda: service.get(ctx, item.id),
        ):
            with pytest.raises(AppError) as caught:
                call()
            assert caught.value.code == "system.dependency_unavailable"


@pytest.mark.parametrize("change", ["disabled", "version"])
def test_global_user_invalidation_blocks_resident_and_extra_identity(
    identity_data: tuple[sessionmaker[Session], ClientAuthorization, list[str]], change: str
) -> None:
    factory, ctx, subjects = identity_data
    with factory() as db:
        service = ClientIdentityService(db, identity_registry(db, "test_staff"))
        item = service.grant(ctx, "test_staff", subjects[0])
        user = db.get(MiniappUser, ctx.user_id)
        assert user is not None
        if change == "disabled":
            user.enabled = False
        else:
            user.session_version += 1
        db.commit()
        for identity_id in ("resident", item.id):
            with pytest.raises(AppError) as caught:
                service.get(ctx, identity_id)
            assert caught.value.code == "auth.unauthenticated"


def test_trusted_grant_validates_subject_and_regrant_never_revives_old_id(
    identity_data: tuple[sessionmaker[Session], ClientAuthorization, list[str]],
) -> None:
    factory, ctx, subjects = identity_data
    with factory() as db:
        service = ClientIdentityService(db, identity_registry(db, "test_staff"))
        for identity_type, subject in (("resident", ctx.user_id), ("test_staff", subjects[3])):
            with pytest.raises(AppError) as caught:
                service.grant(ctx, identity_type, subject)
            assert caught.value.code == "client.identity_unavailable"
        item = service.grant(ctx, "test_staff", subjects[0])
        old = service.authorize(ctx, item.id, expected_type="test_staff")
        assert isinstance(old, ExtraIdentityAuthorization)
        with pytest.raises(AppError) as conflict:
            service.grant(ctx, "test_staff", subjects[0])
        assert conflict.value.code == "resource.conflict"
        with pytest.raises(AppError) as version_conflict:
            service.revoke(ctx, item.id, expected_version=2)
        assert version_conflict.value.code == "resource.conflict"
        service.revoke(ctx, item.id, expected_version=1)
        new = service.grant(ctx, "test_staff", subjects[0])
        assert new.id != item.id
        with pytest.raises(AppError) as unavailable:
            service.protect(old)
        assert unavailable.value.code == "client.identity_unavailable"
        db.commit()
    with factory() as db:
        rows = list(
            db.scalars(select(MiniappUserIdentity).order_by(MiniappUserIdentity.created_at))
        )
        assert [(row.status, row.row_version) for row in rows] == [("revoked", 2), ("active", 1)]


def test_grant_and_revoke_leave_commit_to_caller(
    identity_data: tuple[sessionmaker[Session], ClientAuthorization, list[str]],
) -> None:
    factory, ctx, subjects = identity_data
    with factory() as db:
        service = ClientIdentityService(db, identity_registry(db, "test_staff"))
        item = service.grant(ctx, "test_staff", subjects[0])
        service.revoke(ctx, item.id, expected_version=1)
        db.rollback()
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(MiniappUserIdentity)) == 0


def test_concurrent_grant_has_one_active_link_and_conflicting_call_keeps_transaction_usable(
    identity_data: tuple[sessionmaker[Session], ClientAuthorization, list[str]],
) -> None:
    factory, ctx, subjects = identity_data
    barrier = Barrier(2)

    def grant() -> str:
        with factory() as db:
            service = ClientIdentityService(db, identity_registry(db, "test_staff"))
            barrier.wait(timeout=10)
            try:
                item = service.grant(ctx, "test_staff", subjects[0])
                db.commit()
                return item.id
            except AppError as error:
                assert error.code == "resource.conflict"
                assert service.get(ctx, "resident").id == "resident"
                db.rollback()
                return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: grant(), range(2)))
    assert results.count("conflict") == 1
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(MiniappUserIdentity)) == 1


def test_database_constraints_protect_generic_links(
    identity_data: tuple[sessionmaker[Session], ClientAuthorization, list[str]],
) -> None:
    factory, ctx, subjects = identity_data
    with factory() as db:
        now = utc_now()
        cases: list[tuple[dict[str, object], str]] = [
            ({"identity_type": "resident"}, "ck_miniapp_identity_non_resident"),
            ({"identity_type": "Test_staff"}, "ck_miniapp_identity_type"),
            ({"row_version": 0}, "ck_miniapp_identity_version"),
            ({"status": "revoked"}, "ck_miniapp_identity_status"),
            ({"user_id": new_id()}, "fk_miniapp_identity_user"),
            (
                {"status": "revoked", "revoked_at": now - timedelta(seconds=1)},
                "ck_miniapp_identity_revoked_time",
            ),
        ]
        for changes, expected in cases:
            values: dict[str, object] = {
                "user_id": ctx.user_id,
                "identity_type": "test_staff",
                "subject_id": subjects[0],
                "created_at": now,
                "updated_at": now,
            }
            values.update(changes)
            with pytest.raises(IntegrityError) as caught, db.begin_nested():
                db.execute(insert(MiniappUserIdentity).values(**values))
            assert (
                getattr(getattr(caught.value.orig, "diag", None), "constraint_name", None)
                == expected
            )


def _wait_for_blocked(factory: sessionmaker[Session], pid: int) -> None:
    from time import monotonic, sleep

    from sqlalchemy import text

    deadline = monotonic() + 10
    with factory() as db:
        while monotonic() < deadline:
            blocked = db.scalar(
                text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"), {"pid": pid}
            )
            if blocked:
                return
            sleep(0.01)
    pytest.fail("Identity lifecycle operation did not acquire its expected protection lock")


@pytest.mark.parametrize("first", ["writer", "revoker"])
def test_identity_write_and_revoke_serialize_and_refresh_after_lock_wait(
    identity_data: tuple[sessionmaker[Session], ClientAuthorization, list[str]], first: str
) -> None:
    from sqlalchemy import text

    factory, ctx, subjects = identity_data
    with factory() as db:
        service = ClientIdentityService(db, identity_registry(db, "test_staff"))
        item = service.grant(ctx, "test_staff", subjects[0])
        old = service.authorize(ctx, item.id, expected_type="test_staff")
        assert isinstance(old, ExtraIdentityAuthorization)
        db.commit()
    ready = Event()
    backend_pid: list[int] = []

    def second_operation() -> str:
        with factory() as db:
            backend_pid.append(db.scalar(text("SELECT pg_backend_pid()")))
            ready.set()
            service = ClientIdentityService(db, identity_registry(db, "test_staff"))
            if first == "writer":
                service.revoke(ctx, item.id, expected_version=1)
                db.commit()
                return "revoked"
            try:
                service.protect(old)
                db.execute(
                    update(SUBJECTS).where(SUBJECTS.c.id == subjects[0]).values(name="非法写入")
                )
                db.commit()
                return "wrote"
            except AppError as error:
                assert error.code == "client.identity_unavailable"
                db.rollback()
                return "denied"

    with factory() as db, ThreadPoolExecutor(max_workers=1) as pool:
        service = ClientIdentityService(db, identity_registry(db, "test_staff"))
        if first == "writer":
            service.protect(old)
            db.execute(update(SUBJECTS).where(SUBJECTS.c.id == subjects[0]).values(name="合法写入"))
        else:
            service.revoke(ctx, item.id, expected_version=1)
        future = pool.submit(second_operation)
        try:
            assert ready.wait(10)
            _wait_for_blocked(factory, backend_pid[0])
        finally:
            db.commit()
        assert future.result(timeout=10) == ("revoked" if first == "writer" else "denied")
    with factory() as db:
        row = db.get(MiniappUserIdentity, item.id)
        assert row is not None and row.status == "revoked" and row.row_version == 2
        name = db.scalar(select(SUBJECTS.c.name).where(SUBJECTS.c.id == subjects[0]))
        assert name == ("合法写入" if first == "writer" else "测试主体0")
