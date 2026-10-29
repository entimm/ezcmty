import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from tests.support.paths import BACKEND_ROOT

from backend_app.db.session import get_session_factory
from backend_app.models.housing import House, HouseOwner, SpaceNode
from backend_app.models.property import Community, PropertyCompany


@pytest.mark.parametrize(
    "case,sqlstate,constraint",
    [
        ("root_duplicate", "23505", "uq_space_node_sibling_name"),
        ("child_duplicate", "23505", "uq_space_node_sibling_name"),
        ("cross_community_parent", "23503", "fk_space_node_parent"),
        ("cross_community_house", "23503", "fk_house_space_node"),
        ("noncanonical_phone", "23514", "ck_house_owner_phone"),
        ("self_parent", "23514", "ck_space_node_parent"),
    ],
)
def test_native_housing_constraints(
    migrated_database_url: str, case: str, sqlstate: str, constraint: str
) -> None:
    with get_session_factory()() as db:
        company = PropertyCompany(code="PROPERTY", name="公司")
        db.add(company)
        db.flush()
        first = Community(property_company_id=company.id, code="FIRST", name="一", address="地址")
        second = Community(property_company_id=company.id, code="SECOND", name="二", address="地址")
        db.add_all([first, second])
        db.flush()
        node = SpaceNode(community_id=first.id, name="A", node_type="building")
        db.add(node)
        db.flush()
        unit = SpaceNode(community_id=first.id, parent_id=node.id, name="unit", node_type="unit")
        house = House(community_id=first.id, space_node_id=node.id, room_no="101")
        db.add_all([unit, house])
        db.flush()
        row: SpaceNode | House | HouseOwner
        if case == "root_duplicate":
            node.enabled = False
            db.flush()
            row = SpaceNode(community_id=first.id, name="A", node_type="phase")
        elif case == "child_duplicate":
            row = SpaceNode(community_id=first.id, parent_id=node.id, name="unit", node_type="unit")
        elif case == "cross_community_parent":
            row = SpaceNode(
                community_id=second.id, parent_id=node.id, name="unit", node_type="unit"
            )
        elif case == "cross_community_house":
            row = House(community_id=second.id, space_node_id=node.id, room_no="102")
        elif case == "noncanonical_phone":
            row = HouseOwner(house_id=house.id, name="业主", phone="+8613800000000")
        else:
            row = node
        with pytest.raises(IntegrityError) as caught, db.begin_nested():
            if case == "self_parent":
                node.parent_id = node.id
            else:
                db.add(row)
            db.flush()
        assert getattr(caught.value.orig, "sqlstate", None) == sqlstate
        assert (
            getattr(getattr(caught.value.orig, "diag", None), "constraint_name", None) == constraint
        )
        # Case-sensitive names and duplicate external references remain valid metadata.
        db.add_all(
            [
                SpaceNode(
                    community_id=first.id, name="a", node_type="building", external_code="00X"
                ),
                SpaceNode(
                    community_id=second.id, name="A", node_type="building", external_code="00X"
                ),
            ]
        )
        db.commit()


def test_housing_downgrade_refuses_existing_data_and_keeps_revision(
    migrated_database_url: str,
) -> None:
    with get_session_factory()() as db:
        company = PropertyCompany(code="PROPERTY", name="公司")
        db.add(company)
        db.flush()
        community = Community(
            property_company_id=company.id, code="COMMUNITY", name="小区", address="地址"
        )
        db.add(community)
        db.flush()
        db.add(SpaceNode(community_id=community.id, name="A", node_type="building"))
        db.commit()
    with pytest.raises(RuntimeError, match="housing data exists"):
        command.downgrade(Config(str(BACKEND_ROOT / "alembic.ini")), "20261014_admin_audit_company")
    with get_session_factory()() as db:
        assert db.scalar(select(SpaceNode.name)) == "A"
        assert (
            db.scalar(text("SELECT version_num FROM alembic_version")) == "20261029_business_actors"
        )
