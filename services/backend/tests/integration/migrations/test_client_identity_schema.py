import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import Session
from tests.support.paths import BACKEND_ROOT

from backend_app.core.identifiers import new_id
from backend_app.models.admin import utc_now
from backend_app.models.miniapp import MiniappUser, MiniappUserIdentity


def test_client_migration_preserves_existing_users_and_adds_empty_identity_table(
    database_url: str,
) -> None:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    command.upgrade(config, "20261023_import_preparation")
    engine = create_engine(database_url)
    try:
        with Session(engine) as db:
            users = [
                MiniappUser(wechat_openid="existing-enabled", session_version=7),
                MiniappUser(wechat_openid="existing-disabled", enabled=False, session_version=3),
            ]
            db.add_all(users)
            db.commit()
            before = [
                (user.id, user.wechat_openid, user.enabled, user.session_version) for user in users
            ]
        command.upgrade(config, "head")
        with Session(engine) as db:
            after = [
                (user.id, user.wechat_openid, user.enabled, user.session_version)
                for user in db.scalars(select(MiniappUser).order_by(MiniappUser.wechat_openid))
            ]
            assert sorted(before) == sorted(after)
            assert list(db.scalars(select(MiniappUserIdentity))) == []
        inspector = inspect(engine)
        assert inspector.get_pk_constraint("miniapp_user_identities")["name"] == (
            "pk_miniapp_user_identities"
        )
        foreign_keys = inspector.get_foreign_keys("miniapp_user_identities")
        assert len(foreign_keys) == 1
        assert foreign_keys[0]["constrained_columns"] == ["user_id"]
        assert foreign_keys[0]["referred_table"] == "miniapp_users"
    finally:
        engine.dispose()


def test_empty_client_identity_schema_can_downgrade_and_upgrade_without_touching_users(
    migrated_database_url: str,
) -> None:
    engine = create_engine(migrated_database_url)
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    try:
        with Session(engine) as db:
            user = MiniappUser(wechat_openid="retained-user")
            db.add(user)
            db.commit()
            user_id = user.id
        command.downgrade(config, "20261023_import_preparation")
        assert "miniapp_user_identities" not in inspect(engine).get_table_names()
        with Session(engine) as db:
            assert db.get(MiniappUser, user_id) is not None
        command.upgrade(config, "head")
        with Session(engine) as db:
            assert db.get(MiniappUser, user_id) is not None
            assert list(db.scalars(select(MiniappUserIdentity))) == []
    finally:
        engine.dispose()


@pytest.mark.parametrize("status", ["active", "revoked"])
def test_client_identity_downgrade_refuses_any_grant_history(
    migrated_database_url: str, status: str
) -> None:
    engine = create_engine(migrated_database_url)
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    try:
        with Session(engine) as db:
            user = MiniappUser(wechat_openid="historical-user")
            db.add(user)
            db.flush()
            now = utc_now()
            identity = MiniappUserIdentity(
                user_id=user.id,
                identity_type="historical_subject",
                subject_id=new_id(),
                status=status,
                created_at=now,
                updated_at=now,
                revoked_at=now if status == "revoked" else None,
            )
            db.add(identity)
            db.commit()
            identity_id = identity.id
        with pytest.raises(RuntimeError, match="client identity history exists"):
            command.downgrade(config, "20261023_import_preparation")
        with Session(engine) as db:
            assert db.get(MiniappUserIdentity, identity_id) is not None
            assert db.scalar(text("SELECT version_num FROM alembic_version")) == (
                "20261027_client_identities"
            )
    finally:
        engine.dispose()
