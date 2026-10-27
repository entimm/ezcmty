from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend_app.core.errors import AppError
from backend_app.core.identifiers import new_id, normalize_uuid
from backend_app.domain.client.registry import IdentityProvider, IdentityRegistry
from backend_app.domain.client.types import (
    ClientAuthorization,
    ClientIdentityDescriptor,
    ExtraIdentityAuthorization,
    IdentityResolution,
)
from backend_app.models.admin import utc_now
from backend_app.models.miniapp import MiniappUserIdentity
from backend_app.repositories.client_identities import (
    ClientIdentityRepository,
    IdentityDirectorySource,
)
from backend_app.repositories.miniapp import MiniappRepository


class ClientIdentityRegistry:
    """Finite application assembly pairing pure providers with SQL directory sources."""

    def __init__(self) -> None:
        self.providers = IdentityRegistry()
        self._sources: dict[str, IdentityDirectorySource] = {}

    def register(self, provider: IdentityProvider, source: IdentityDirectorySource) -> None:
        self.providers.register(provider)
        self._sources[provider.identity_type] = source

    def sources(self) -> dict[str, IdentityDirectorySource]:
        return {
            provider.identity_type: self._sources[provider.identity_type]
            for provider in self.providers.providers()
        }


class ClientIdentityService:
    def __init__(self, db: Session, registry: ClientIdentityRegistry | None = None):
        self.db = db
        self.registry = registry if registry is not None else ClientIdentityRegistry()
        self.users = MiniappRepository(db)
        self.links = ClientIdentityRepository(db)

    def list(
        self, ctx: ClientAuthorization, *, page: int, page_size: int
    ) -> tuple[list[ClientIdentityDescriptor], int]:
        self.users.user(ctx.user_id, ctx.version)
        return self.links.list(ctx.user_id, self.registry.sources(), page=page, page_size=page_size)

    def get(self, ctx: ClientAuthorization, identity_id: str) -> ClientIdentityDescriptor:
        self.users.user(ctx.user_id, ctx.version)
        if identity_id == "resident":
            return ClientIdentityDescriptor("resident", "resident", "居民")
        item = self._owned(ctx, identity_id)
        resolution = self._resolve(ctx, item, lock=False)
        return ClientIdentityDescriptor(item.id, item.identity_type, resolution.display_name)

    def authorize(
        self, ctx: ClientAuthorization, identity_id: str, *, expected_type: str, lock: bool = False
    ) -> ClientAuthorization:
        self.users.user(ctx.user_id, ctx.version)
        if identity_id == "resident":
            if expected_type != "resident":
                raise AppError("client.identity_mismatch")
            self.users.user(ctx.user_id, ctx.version, lock=lock)
            return ClientAuthorization(ctx.user_id, ctx.version)
        item = self._owned(ctx, identity_id)
        resolution = self._resolve(ctx, item, lock=lock)
        if item.identity_type != expected_type:
            raise AppError("client.identity_mismatch")
        return resolution.authorization

    def protect(self, ctx: ExtraIdentityAuthorization) -> ExtraIdentityAuthorization:
        """Recheck a previously resolved context under write-protection locks."""
        current = self.authorize(ctx, ctx.identity_id, expected_type=ctx.identity_type, lock=True)
        if not isinstance(current, ExtraIdentityAuthorization) or (
            current.subject_id != ctx.subject_id or current.row_version != ctx.row_version
        ):
            raise AppError("client.identity_unavailable")
        return current

    def grant(
        self, ctx: ClientAuthorization, identity_type: str, subject_id: str
    ) -> ClientIdentityDescriptor:
        """Trusted grant entry; caller supplies business authority, audit and commit."""
        self.users.user(ctx.user_id, ctx.version)
        provider = self.registry.providers.get(identity_type)
        if provider is None:
            raise AppError("client.identity_unavailable")
        now = utc_now()
        item = MiniappUserIdentity(
            id=new_id(),
            user_id=ctx.user_id,
            identity_type=identity_type,
            subject_id=normalize_uuid(subject_id),
            status="active",
            row_version=1,
            created_at=now,
            updated_at=now,
        )
        snapshot = self.links.snapshot(item)
        provider.lock_parent(ctx, snapshot)
        self.users.user(ctx.user_id, ctx.version, lock=True)
        resolution = provider.resolve(ctx, snapshot, lock=True)
        self._validate_resolution(ctx, item, resolution)
        try:
            with self.db.begin_nested():
                self.db.add(item)
                self.db.flush()
        except IntegrityError as error:
            if getattr(getattr(error.orig, "diag", None), "constraint_name", None) != (
                "uq_miniapp_identity_active"
            ):
                raise
            raise AppError("resource.conflict") from None
        assert resolution is not None
        return ClientIdentityDescriptor(item.id, item.identity_type, resolution.display_name)

    def revoke(self, ctx: ClientAuthorization, identity_id: str, *, expected_version: int) -> None:
        """Trusted transaction entry; caller owns authorization, audit and commit."""
        self.users.user(ctx.user_id, ctx.version)
        item = self._owned(ctx, identity_id)
        provider = self.registry.providers.get(item.identity_type)
        if provider is not None:
            provider.lock_parent(ctx, self.links.snapshot(item))
        self.users.user(ctx.user_id, ctx.version, lock=True)
        self.links.revoke(ctx.user_id, item.id, expected_version)

    def _owned(self, ctx: ClientAuthorization, identity_id: str) -> MiniappUserIdentity:
        try:
            normalized = normalize_uuid(identity_id)
        except ValueError:
            raise AppError("resource.not_found") from None
        return self.links.owned(ctx.user_id, normalized)

    def _resolve(
        self, ctx: ClientAuthorization, item: MiniappUserIdentity, *, lock: bool
    ) -> IdentityResolution:
        provider = self.registry.providers.get(item.identity_type)
        if item.status != "active" or provider is None:
            raise AppError("client.identity_unavailable")
        if lock:
            # Immutable ownership permits an initial read solely to locate ancestor locks.
            provider.lock_parent(ctx, self.links.snapshot(item))
            self.users.user(ctx.user_id, ctx.version, lock=True)
            item = self.links.owned(ctx.user_id, item.id, lock=True)
            if item.status != "active":
                raise AppError("client.identity_unavailable")
        resolution = provider.resolve(ctx, self.links.snapshot(item), lock=lock)
        self._validate_resolution(ctx, item, resolution)
        assert resolution is not None
        return resolution

    @staticmethod
    def _validate_resolution(
        ctx: ClientAuthorization,
        item: MiniappUserIdentity,
        resolution: IdentityResolution | None,
    ) -> None:
        if resolution is None:
            raise AppError("client.identity_unavailable")
        auth = resolution.authorization
        if (
            auth.user_id != ctx.user_id
            or auth.version != ctx.version
            or auth.identity_id != item.id
            or auth.identity_type != item.identity_type
            or auth.subject_id != item.subject_id
            or auth.row_version != item.row_version
            or not resolution.display_name.strip()
            or len(resolution.display_name) > 160
        ):
            raise ValueError("Provider returned an invalid identity resolution")
