from uuid import uuid4

import pytest

from backend_app.core.errors import AppError
from backend_app.domain.housing import HouseOwnerCreationCommand, InitialHouseOwner


@pytest.mark.parametrize("phone", ["13800000000", "+8613800000000", "008613800000000"])
def test_owner_command_uses_initial_owner_rules_and_normalized_identity(phone: str) -> None:
    house_id = str(uuid4())
    command = HouseOwnerCreationCommand.from_input(
        {"house_id": house_id.upper(), "name": " 张甲 ", "phone": f" {phone} "}
    )
    initial = InitialHouseOwner(" 张甲 ", phone)
    assert command.to_dict() == {
        "house_id": house_id,
        "name": initial.name,
        "phone": initial.phone,
    }
    canonical = HouseOwnerCreationCommand(house_id, "张甲", "13800000000")
    assert command == canonical
    assert command.fingerprint() == canonical.fingerprint()
    assert HouseOwnerCreationCommand.from_input(command.to_dict()) == command


@pytest.mark.parametrize(
    "changes",
    [
        {"house_id": "invalid"},
        {"house_id": None},
        {"name": " "},
        {"name": "x" * 81},
        {"name": 123},
        {"phone": "12800000000"},
        {"phone": "+86+8613800000000"},
        {"phone": "138-0000-0000"},
        {"phone": 13800000000},
        {"phone": None},
        {"enabled": True},
    ],
)
def test_owner_command_rejects_invalid_business_input(changes: dict[str, object]) -> None:
    with pytest.raises(AppError) as caught:
        HouseOwnerCreationCommand.from_input(
            {"house_id": str(uuid4()), "name": "业主", "phone": "13800000000", **changes}
        )
    assert caught.value.code == "VALIDATION_ERROR"


def test_owner_identity_keeps_house_name_and_phone_independent() -> None:
    house_id = str(uuid4())
    base = HouseOwnerCreationCommand(house_id, "张甲", "13800000000")
    alternatives = (
        HouseOwnerCreationCommand(str(uuid4()), "张甲", "13800000000"),
        HouseOwnerCreationCommand(house_id, "张乙", "13800000000"),
        HouseOwnerCreationCommand(house_id, "张甲", "13900000000"),
    )
    assert all(base.fingerprint() != command.fingerprint() for command in alternatives)
