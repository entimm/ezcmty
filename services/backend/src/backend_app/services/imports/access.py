from datetime import datetime
from typing import cast

from sqlalchemy.orm import Session

from backend_app.core.config import Settings
from backend_app.core.errors import AppError
from backend_app.domain.admin.identity import AdminIdentity
from backend_app.domain.admin.types import AdminScope
from backend_app.domain.imports.registry import ImportDefinition, ImportRegistry
from backend_app.import_definitions.catalog import get_import_registry
from backend_app.integrations.import_files.storage import LocalImportStorage
from backend_app.models.admin import AdminAccount
from backend_app.models.imports import ImportBatch
from backend_app.repositories.admin import AdminRepository
from backend_app.repositories.imports.batches import get_batch
from backend_app.repositories.property import PropertyRepository
from backend_app.services.contracts.admin import AdminContext
from backend_app.services.imports.permissions import batch_permissions, require_permissions
from backend_app.services.worker.imports.adapters.base import ImportAdapter


class ImportAccess:
    scope: AdminScope

    def __init__(
        self,
        db: Session,
        settings: Settings,
        *,
        registry: ImportRegistry | None = None,
        storage: LocalImportStorage | None = None,
    ) -> None:
        self.db = db
        self.settings = settings
        self.registry = registry if registry is not None else get_import_registry()
        self._storage = storage
        self.repo = PropertyRepository(db)
        self.prefix = "platform" if self.scope == "platform_admin" else "property"

    @property
    def storage(self) -> LocalImportStorage:
        if self._storage is None:
            self._storage = LocalImportStorage(self.settings.import_storage_root)
        return self._storage

    def company_id(
        self, ctx: AdminContext, requested: str | None, *, creating: bool = False
    ) -> str | None:
        raise NotImplementedError

    def authorize(
        self, ctx: AdminContext, permission: str
    ) -> tuple[AdminIdentity, AdminAccount, frozenset[str]]:
        if ctx.scope != self.scope:
            raise AppError("auth.forbidden")
        repo = AdminRepository(self.db, self.scope)
        identity = AdminIdentity(repo)
        actor = identity.session_account(ctx.account_id, ctx.version)
        identity.bind_account(actor)
        identity.require_full_session(identity.authorization(actor))
        permissions = frozenset(identity.effective_permissions(actor.id))
        if f"{self.prefix}.import.{permission}" not in permissions:
            raise AppError("auth.forbidden")
        if self.scope == "property_admin":
            company = self.repo.company(actor.property_company_id or "")
            if company is None or not company.enabled:
                raise AppError("auth.unauthenticated")
        return (identity, actor, permissions)

    def definition(
        self,
        key: str,
        version: int,
        permissions: frozenset[str],
        config_hash: str | None = None,
        *,
        missing_not_found: bool = False,
        for_write: bool = True,
    ) -> ImportDefinition:
        try:
            definition = self.registry.get(key, version, config_hash)
        except ValueError as error:
            code = str(error)
            if missing_not_found and code == "import.template_unavailable":
                code = "resource.not_found"
            raise AppError(
                code
                if code
                in {"import.template_unavailable", "import.template_drift", "resource.not_found"}
                else "import.template_unavailable"
            ) from None
        if self.scope not in definition.allowed_actor_scopes:
            raise AppError("resource.not_found")
        required = definition.required_permissions if for_write else definition.read_permissions
        if not set(required) <= permissions:
            raise AppError("auth.forbidden")
        return definition

    def target(self, ctx: AdminContext, batch_id: str, *, lock: bool = False) -> ImportBatch:
        batch = get_batch(
            self.db,
            batch_id,
            property_company_id=self.company_id(ctx, None),
            actor_scope=self.scope,
            lock=lock,
        )
        if batch is None:
            raise AppError("resource.not_found")
        return batch

    def check_scope(self, batch: ImportBatch, *, writing: bool = True) -> None:
        company = self.repo.company(batch.property_company_id)
        if company is None:
            raise AppError("resource.not_found")
        if writing and (not company.enabled):
            raise AppError("auth.forbidden")
        if batch.community_id:
            community = self.repo.community(
                batch.community_id, company_scope_id=batch.property_company_id
            )
            if community is None:
                raise AppError("resource.not_found")
            if writing and (not community.enabled):
                raise AppError("auth.forbidden")

    def check_business_permissions(self, batch: ImportBatch, permissions: frozenset[str]) -> None:
        definition = self.definition(
            batch.template_key, batch.template_version_no, permissions, batch.template_config_hash
        )
        adapter = cast(ImportAdapter, self.registry.get_adapter(definition.adapter_key))
        require_permissions(batch_permissions(self.db, batch, definition, adapter), permissions)

    @staticmethod
    def alive(batch: ImportBatch, now: datetime) -> None:
        if now >= batch.retention_until:
            raise AppError("import.data_expired")
