import re
from typing import Protocol

from backend_app.domain.client.types import ClientAuthorization, IdentityLink, IdentityResolution


class IdentityProvider(Protocol):
    """A statically registered application adapter; no HTTP, Redis or SQL contract."""

    @property
    def identity_type(self) -> str: ...

    @property
    def enabled(self) -> bool: ...

    def lock_parent(self, user: ClientAuthorization, link: IdentityLink) -> None:
        """Protect company/account ancestors before the framework locks user and link."""
        ...

    def resolve(
        self, user: ClientAuthorization, link: IdentityLink, *, lock: bool
    ) -> IdentityResolution | None:
        """Resolve current subject facts; protect downstream rows when lock is requested."""
        ...


class IdentityRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, IdentityProvider] = {}

    def register(self, provider: IdentityProvider) -> None:
        code = provider.identity_type
        if code == "resident" or re.fullmatch(r"[a-z][a-z0-9_]{0,31}", code) is None:
            raise ValueError("Extra identity type must be canonical and cannot be resident")
        if code in self._providers:
            raise ValueError("Identity type is already registered")
        self._providers[code] = provider

    def get(self, code: str) -> IdentityProvider | None:
        provider = self._providers.get(code)
        return provider if provider is not None and provider.enabled else None

    def providers(self) -> tuple[IdentityProvider, ...]:
        return tuple(provider for provider in self._providers.values() if provider.enabled)
