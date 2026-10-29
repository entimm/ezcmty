from dataclasses import dataclass
from datetime import date

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Connection, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from tests.support.paths import BACKEND_ROOT

from backend_app.core.identifiers import new_id
from backend_app.db.base import Base
from backend_app.db.session import get_engine
from backend_app.models.admin import AdminAccount, utc_now
from backend_app.models.billing import Bill, BillOperation
from backend_app.models.house_claims import HouseClaim, ResidentHouseBinding
from backend_app.models.housing import House, SpaceNode
from backend_app.models.miniapp import MiniappUser
from backend_app.models.property import Community, PropertyCompany

PREVIOUS_REVISION = "20261027_client_identities"
ACTOR_REVISION = "20261029_business_actors"
ACTOR_KEYS = (
    ("bill_operations", "actor_id", "fk_bill_operation_actor"),
    ("house_claim_applications", "reviewed_by_admin_id", "fk_house_claim_reviewer"),
    ("resident_house_bindings", "ended_by_admin_id", "fk_resident_binding_admin"),
)


@dataclass(frozen=True)
class ActorData:
    company_id: str
    community_id: str
    node_id: str
    user_id: str
    property_actor_id: str
    platform_actor_id: str
    other_company_actor_id: str


def _provision(db: Session) -> ActorData:
    company = PropertyCompany(code="ACTORS", name="业务公司", enabled=True)
    other = PropertyCompany(code="OTHER", name="另一公司", enabled=True)
    user = MiniappUser(wechat_openid="actor-schema-resident")
    db.add_all([company, other, user])
    db.flush()
    community = Community(
        property_company_id=company.id, code="ACTORS", name="小区", address="地址"
    )
    account = AdminAccount(
        scope="property_admin",
        property_company_id=company.id,
        login_name="property.actor",
        display_name="物业操作者",
        password_hash="migration-test-hash",
        must_change_password=False,
    )
    platform = AdminAccount(
        scope="platform_admin",
        login_name="platform.actor",
        display_name="平台操作者",
        password_hash="migration-test-hash",
        must_change_password=False,
    )
    other_account = AdminAccount(
        scope="property_admin",
        property_company_id=other.id,
        login_name="other.actor",
        display_name="另一公司操作者",
        password_hash="migration-test-hash",
        must_change_password=False,
    )
    db.add_all([community, account, platform, other_account])
    db.flush()
    node = SpaceNode(community_id=community.id, node_type="building", name="楼栋")
    db.add(node)
    db.flush()
    return ActorData(
        company.id, community.id, node.id, user.id, account.id, platform.id, other_account.id
    )


@pytest.fixture
def actor_data(migrated_database_url: str) -> ActorData:
    with Session(get_engine()) as db:
        data = _provision(db)
        db.commit()
        return data


def _history(db: Session, data: ActorData, actors: dict[str, str | None] | None = None) -> None:
    actors = actors or {}
    now = utc_now()
    house_id = new_id()
    house = House(
        id=house_id,
        community_id=data.community_id,
        space_node_id=data.node_id,
        room_no=house_id[-12:],
    )
    db.add(house)
    db.flush()
    bill = Bill(
        id=new_id(),
        property_company_id=data.company_id,
        community_id=data.community_id,
        house_id=house.id,
        bill_type="property_fee",
        period_granularity="month",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 2, 1),
        amount_source="manual",
        receivable_cents=100,
        settled_cents=0,
        lifecycle_status="active",
        house_label_snapshot="楼栋/房屋",
        manual_amount_reason="历史账单",
        row_version=1,
        created_by=data.property_actor_id,
        created_at=now,
        updated_at=now,
    )
    db.add(bill)
    db.flush()
    db.add(
        BillOperation(
            id=new_id(),
            property_company_id=data.company_id,
            bill_id=bill.id,
            bill_version=1,
            action="create",
            idempotency_key=new_id(),
            request_fingerprint="a" * 64,
            result={"bill_id": bill.id},
            response_status=201,
            actor_type="admin",
            actor_id=actors.get("actor_id", data.property_actor_id),
            request_id="migration-history",
            created_at=now,
        )
    )
    db.flush()
    reviewer = actors.get("reviewed_by_admin_id", data.property_actor_id)
    claim = HouseClaim(
        id=new_id(),
        user_id=data.user_id,
        property_company_id=data.company_id,
        community_id=data.community_id,
        house_id=house.id,
        house_label_snapshot="楼栋/房屋",
        applicant_name="居民",
        applicant_phone="13800138000",
        match_status="unmatched",
        status="approved" if reviewer else "pending",
        reviewed_by_admin_id=reviewer,
        reviewed_at=now if reviewer else None,
        review_reason="人工核验" if reviewer else None,
        row_version=1,
        idempotency_key=new_id(),
        request_fingerprint="b" * 64,
        created_at=now,
        updated_at=now,
    )
    db.add(claim)
    db.flush()
    if reviewer is not None:
        ender = actors.get("ended_by_admin_id", data.property_actor_id)
        db.add(
            ResidentHouseBinding(
                id=new_id(),
                user_id=data.user_id,
                property_company_id=data.company_id,
                community_id=data.community_id,
                house_id=house.id,
                claim_application_id=claim.id,
                status="revoked" if ender else "active",
                granted_at=now,
                ended_at=now if ender else None,
                ended_by_admin_id=ender,
                end_reason="结束授权" if ender else None,
                row_version=1,
                created_at=now,
                updated_at=now,
            )
        )
        db.flush()


def _schema(connection: Connection) -> dict[str, list[tuple[object, ...]]]:
    queries = {
        "columns": """SELECT c.relname,a.attname,format_type(a.atttypid,a.atttypmod),
            a.attnotnull,pg_get_expr(d.adbin,d.adrelid),a.attidentity,a.attgenerated
            FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            JOIN pg_attribute a ON a.attrelid=c.oid
            LEFT JOIN pg_attrdef d ON d.adrelid=c.oid AND d.adnum=a.attnum
            WHERE n.nspname='public' AND c.relkind='r' AND a.attnum>0 AND NOT a.attisdropped
            ORDER BY c.relname,a.attnum""",
        "constraints": """SELECT c.relname,k.conname,pg_get_constraintdef(k.oid)
            FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid
            JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='public' AND k.conname NOT IN
            ('fk_bill_operation_actor','fk_house_claim_reviewer','fk_resident_binding_admin')
            ORDER BY c.relname,k.conname""",
        "indexes": """SELECT tablename,indexname,indexdef FROM pg_indexes
            WHERE schemaname='public' ORDER BY tablename,indexname""",
        "triggers": """SELECT c.relname,t.tgname,pg_get_triggerdef(t.oid)
            FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
            JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='public' AND NOT t.tgisinternal ORDER BY c.relname,t.tgname""",
        "functions": """SELECT p.proname,pg_get_functiondef(p.oid)
            FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
            WHERE n.nspname='public' ORDER BY p.proname""",
    }
    return {
        name: [tuple(row) for row in connection.execute(text(query))]
        for name, query in queries.items()
    }


def _data(connection: Connection) -> dict[str, list[object]]:
    result: dict[str, list[object]] = {}
    for table in inspect(connection).get_table_names():
        if table != "alembic_version":
            identifier = connection.dialect.identifier_preparer.quote(table)
            result[table] = list(
                connection.scalars(
                    text(f"SELECT to_jsonb(t) FROM {identifier} t ORDER BY to_jsonb(t)::text")
                )
            )
    return result


def _assert_actor_keys(connection: Connection, *, company_scoped: bool) -> None:
    inspector = inspect(connection)
    for table, actor_column, constraint in ACTOR_KEYS:
        actual = next(
            item for item in inspector.get_foreign_keys(table) if item["name"] == constraint
        )
        assert actual["referred_table"] == "admin_accounts"
        assert actual["constrained_columns"] == (
            ["property_company_id", actor_column] if company_scoped else [actor_column]
        )
        assert actual["referred_columns"] == (
            ["property_company_id", "id"] if company_scoped else ["id"]
        )
        assert actual["options"].get("ondelete", "NO ACTION") == "NO ACTION"


def test_actor_migration_changes_only_three_keys_and_preserves_compatible_history(
    database_url: str,
) -> None:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    command.upgrade(config, PREVIOUS_REVISION)
    with Session(get_engine()) as db:
        data = _provision(db)
        _history(db, data)
        _history(db, data, {"reviewed_by_admin_id": None})
        _history(db, data, {"ended_by_admin_id": None})
        db.commit()
    with get_engine().connect() as connection:
        before_schema = _schema(connection)
        before_data = _data(connection)
        _assert_actor_keys(connection, company_scoped=True)
    command.upgrade(config, "head")
    with get_engine().connect() as connection:
        _assert_actor_keys(connection, company_scoped=False)
        assert _schema(connection) == before_schema
        assert _data(connection) == before_data
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
    command.downgrade(config, PREVIOUS_REVISION)
    with get_engine().connect() as connection:
        _assert_actor_keys(connection, company_scoped=True)
        assert _schema(connection) == before_schema
        assert _data(connection) == before_data
    command.upgrade(config, "head")
    with get_engine().connect() as connection:
        _assert_actor_keys(connection, company_scoped=False)
        assert _data(connection) == before_data


@pytest.mark.parametrize("table,actor_column,constraint", ACTOR_KEYS)
@pytest.mark.parametrize("actor_kind", ["platform", "other_company"])
def test_cross_company_actor_history_is_valid_and_blocks_downgrade_without_data_loss(
    actor_data: ActorData, table: str, actor_column: str, constraint: str, actor_kind: str
) -> None:
    actor_id = (
        actor_data.platform_actor_id
        if actor_kind == "platform"
        else actor_data.other_company_actor_id
    )
    with Session(get_engine()) as db:
        _history(db, actor_data, {actor_column: actor_id})
        db.commit()
    with get_engine().connect() as connection:
        before_data = _data(connection)
        before_schema = _schema(connection)
        assert connection.scalar(text(f"SELECT {actor_column}::text FROM {table}")) == actor_id
    with pytest.raises(RuntimeError, match="cross-company actor history exists"):
        command.downgrade(Config(str(BACKEND_ROOT / "alembic.ini")), PREVIOUS_REVISION)
    with get_engine().connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == ACTOR_REVISION
        _assert_actor_keys(connection, company_scoped=False)
        assert _data(connection) == before_data
        assert _schema(connection) == before_schema


@pytest.mark.parametrize("table,actor_column,constraint", ACTOR_KEYS)
def test_single_account_foreign_keys_still_reject_missing_actors(
    actor_data: ActorData, table: str, actor_column: str, constraint: str
) -> None:
    with Session(get_engine()) as db:
        with pytest.raises(IntegrityError) as caught:
            _history(db, actor_data, {actor_column: new_id()})
            db.commit()
        db.rollback()
        assert getattr(caught.value.orig, "sqlstate", None) == "23503"
        assert (
            getattr(getattr(caught.value.orig, "diag", None), "constraint_name", None) == constraint
        )
        assert db.scalar(text(f"SELECT count(*) FROM {table}")) == 0
