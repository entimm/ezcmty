from uuid import uuid4

import pytest

from backend_app.core.errors import AppError
from backend_app.domain.housing import HouseCreationCommand, house_creation_permissions


def test_plain_creation_normalizes_house_and_initial_owners_without_http_models() -> None:
    command = HouseCreationCommand.from_input(
        {
            "space_node_id": str(uuid4()),
            "room_no": " 0001A ",
            "floor_no": -1,
            "external_code": " 00a ",
            "owners": [{"name": " 张甲 ", "phone": " +8613800000000 "}],
        }
    )
    assert (command.room_no, command.external_code) == ("0001A", "00a")
    assert (command.owners[0].name, command.owners[0].phone) == ("张甲", "13800000000")
    assert HouseCreationCommand.from_input(command.to_dict()) == command
    assert house_creation_permissions(has_owners=True) == {
        "property.house.create",
        "property.house_owner.create",
    }


@pytest.mark.parametrize(
    "changes",
    [
        {"room_no": " "},
        {"room_no": "x" * 33},
        {"floor_no": True},
        {"floor_no": 1.5},
        {"floor_no": 32768},
        {"floor_no": -32769},
        {"external_code": "x" * 65},
        {"space_node_id": "invalid"},
        {"owners": [{"name": "业主", "phone": "invalid"}]},
        {"owners": [{"name": "", "phone": "13800000000"}]},
        {"unexpected": True},
    ],
)
def test_plain_creation_enforces_business_boundaries(changes: dict[str, object]) -> None:
    with pytest.raises(AppError) as caught:
        HouseCreationCommand.from_input(
            {"space_node_id": str(uuid4()), "room_no": "0001", **changes}
        )
    assert caught.value.code == "VALIDATION_ERROR"


def test_initial_owners_are_deduplicated_after_normalization() -> None:
    with pytest.raises(AppError) as caught:
        HouseCreationCommand.from_input(
            {
                "space_node_id": str(uuid4()),
                "room_no": "001",
                "owners": [
                    {"name": " 业主 ", "phone": "+8613800000000"},
                    {"name": "业主", "phone": "13800000000"},
                ],
            }
        )
    assert caught.value.code == "property.duplicate_house_owner"


def test_basic_content_compares_current_fields_independently_of_initial_owners() -> None:
    data = {"space_node_id": str(uuid4()), "room_no": "0001", "external_code": " "}
    basic = HouseCreationCommand.from_input(data)
    with_owner = HouseCreationCommand.from_input(
        {**data, "owners": [{"name": "业主", "phone": "13800000000"}]}
    )
    assert basic.content() == with_owner.content()
    assert basic.fingerprint() == with_owner.fingerprint()
    assert basic.external_code is None
    assert (
        basic.fingerprint()
        != HouseCreationCommand.from_input({**data, "floor_no": 1}).fingerprint()
    )
