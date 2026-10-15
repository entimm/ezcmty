import pytest
from pydantic import ValidationError

from backend_app.schemas.housing import HouseOwnerCreate


@pytest.mark.parametrize("phone", ["13800000000", "+8613800000000", "008613800000000"])
def test_owner_phone_is_canonical_after_optional_country_prefix(phone: str) -> None:
    owner = HouseOwnerCreate(name=" 姓名 ", phone=phone)
    assert owner.phone == "13800000000" and owner.name == "姓名"


@pytest.mark.parametrize(
    "phone", ["+86+8613800000000", "0086+8613800000000", "123", "12800000000", "138-0000-0000"]
)
def test_malformed_owner_phone_never_reaches_database(phone: str) -> None:
    with pytest.raises(ValidationError):
        HouseOwnerCreate(name="姓名", phone=phone)
