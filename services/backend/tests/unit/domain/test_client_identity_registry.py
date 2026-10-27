import pytest
from tests.support.client_identities import TestIdentityProvider

from backend_app.domain.client.registry import IdentityRegistry


@pytest.mark.parametrize("code", ["resident", "", "Property", " property", "a" * 33])
def test_extra_registry_rejects_reserved_or_noncanonical_type(code: str) -> None:
    registry = IdentityRegistry()
    provider = object.__new__(TestIdentityProvider)
    provider.identity_type = code
    provider.enabled = True
    with pytest.raises(ValueError):
        registry.register(provider)


def test_duplicate_registration_fails_and_closed_provider_is_not_available() -> None:
    provider = object.__new__(TestIdentityProvider)
    provider.identity_type = "test_staff"
    provider.enabled = True
    registry = IdentityRegistry()
    registry.register(provider)
    assert registry.get("test_staff") is provider
    with pytest.raises(ValueError, match="already registered"):
        registry.register(provider)
    provider.enabled = False
    assert registry.get("test_staff") is None
    assert registry.providers() == ()
