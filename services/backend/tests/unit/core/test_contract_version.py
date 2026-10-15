import pytest

from backend_app.core.config import Settings
from backend_app.core.error_catalog import CONTRACT_VERSION


def test_configuration_cannot_claim_a_different_contract_version() -> None:
    with pytest.raises(ValueError, match="APP_VERSION"):
        Settings(version="wrong-revision")
    assert Settings().version == CONTRACT_VERSION
