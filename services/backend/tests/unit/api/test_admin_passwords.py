from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from backend_app.schemas.admin import AccountCreate, AdminLogin, PasswordChange, PasswordReset
from backend_app.schemas.property import PropertyAdminCreate


@pytest.fixture(
    params=[
        pytest.param(
            (PasswordChange, "new_password", {"current_password": "existing"}), id="change"
        ),
        pytest.param((PasswordReset, "password", {}), id="reset"),
        pytest.param(
            (AccountCreate, "password", {"login_name": "audit", "display_name": "管理员"}),
            id="create",
        ),
        pytest.param(
            (PropertyAdminCreate, "password", {"login_name": "audit", "display_name": "管理员"}),
            id="company-admin",
        ),
    ]
)
def new_password_request(
    request: pytest.FixtureRequest,
) -> tuple[type[BaseModel], str, dict[str, Any]]:
    model, field, payload = request.param
    return model, field, payload


@pytest.mark.parametrize(
    "password",
    [
        pytest.param("a" * 12, id="minimum-lowercase"),
        pytest.param("a" * 128, id="maximum-ascii"),
        pytest.param(" " * 12, id="spaces"),
        pytest.param("  " + "😀" * 124 + "  ", id="maximum-unicode-with-spaces"),
        pytest.param("e\u0301" * 6, id="decomposed-unicode"),
    ],
)
def test_new_password_is_preserved_without_character_composition_requirements(
    new_password_request: tuple[type[BaseModel], str, dict[str, Any]], password: str
) -> None:
    model, field, payload = new_password_request
    parsed = model.model_validate({**payload, field: password})
    assert getattr(parsed, field) == password


@pytest.mark.parametrize(
    "password",
    [
        pytest.param("", id="empty"),
        pytest.param("a", id="one"),
        pytest.param("a" * 11, id="below-minimum"),
        pytest.param("😀" * 129, id="above-maximum"),
        pytest.param("\n" + "a" * 12, id="leading-lf"),
        pytest.param("a" * 6 + "\n" + "a" * 6, id="middle-lf"),
        pytest.param("a" * 12 + "\n", id="trailing-lf"),
        pytest.param("\r" + "a" * 12, id="leading-cr"),
        pytest.param("a" * 6 + "\r" + "a" * 6, id="middle-cr"),
        pytest.param("a" * 12 + "\r", id="trailing-cr"),
        pytest.param("a" * 12 + "\r\n", id="trailing-crlf"),
    ],
)
def test_new_password_rejects_invalid_lengths_and_line_breaks(
    new_password_request: tuple[type[BaseModel], str, dict[str, Any]], password: str
) -> None:
    model, field, payload = new_password_request
    with pytest.raises(ValidationError) as caught:
        model.model_validate({**payload, field: password})
    assert caught.value.errors()[0]["loc"] == (field,)


@pytest.mark.parametrize("field", ["login", "current"])
@pytest.mark.parametrize(
    "password",
    [
        pytest.param("a", id="minimum"),
        pytest.param("a" * 11, id="below-new-password-minimum"),
        pytest.param("😀" * 128, id="maximum-unicode"),
        pytest.param(" \rlegacy\n ", id="legacy-line-breaks-and-spaces"),
    ],
)
def test_existing_password_keeps_original_credential_compatibility(
    field: str, password: str
) -> None:
    if field == "login":
        assert AdminLogin(login_name="audit", password=password).password == password
    else:
        assert (
            PasswordChange(current_password=password, new_password="a" * 12).current_password
            == password
        )


@pytest.mark.parametrize("field", ["login", "current"])
@pytest.mark.parametrize("password", ["", "😀" * 129], ids=["empty", "above-maximum"])
def test_existing_password_rejects_only_out_of_range_lengths(field: str, password: str) -> None:
    with pytest.raises(ValidationError):
        if field == "login":
            AdminLogin(login_name="audit", password=password)
        else:
            PasswordChange(current_password=password, new_password="a" * 12)
