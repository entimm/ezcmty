import pytest

from backend_app.core.errors import AppError


@pytest.mark.parametrize("code", ["unregistered.error", "HTTP_ERROR"])
def test_business_error_rejects_invalid_definitions(code: str) -> None:
    with pytest.raises(ValueError):
        AppError(code)
