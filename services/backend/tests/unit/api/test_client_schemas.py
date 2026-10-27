import pytest
from pydantic import ValidationError

from backend_app.core.identifiers import new_id
from backend_app.schemas.miniapp import ClientIdentity


def test_identity_projection_accepts_derived_and_associated_identities() -> None:
    assert ClientIdentity(id="resident", type="resident", display_name="居民").id == "resident"
    key = new_id()
    assert ClientIdentity(id=key, type="future_staff", display_name="业务身份").id == key


@pytest.mark.parametrize(
    "projection",
    [
        {"id": "resident", "type": "resident", "display_name": "伪造名称"},
        {"id": "resident", "type": "future_staff", "display_name": "居民"},
        {"id": "resident", "type": "resident", "display_name": "居民", "subject_id": "hidden"},
        {"id": "unknown", "type": "future_staff", "display_name": "身份"},
        {"id": new_id(), "type": "resident", "display_name": "居民"},
        {"id": new_id(), "type": "UPPERCASE", "display_name": "身份"},
        {"id": new_id(), "type": "future_staff", "display_name": ""},
    ],
)
def test_identity_projection_rejects_mixed_keys_types_and_private_fields(
    projection: dict[str, str],
) -> None:
    with pytest.raises(ValidationError):
        ClientIdentity.model_validate(projection)
