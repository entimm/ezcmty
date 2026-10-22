from typing import Any, BinaryIO

from sqlalchemy.orm import Session

from backend_app.core.config import Settings
from backend_app.domain.imports.registry import ImportRegistry
from backend_app.integrations.import_files.storage import LocalImportStorage
from backend_app.schemas import imports as schema
from backend_app.services.contracts.admin import AdminContext
from backend_app.services.imports.access import ImportAccess
from backend_app.services.imports.artifacts import FileDownload
from backend_app.services.imports.catalog import ImportCatalog
from backend_app.services.imports.control_plane import ImportControlPlane
from backend_app.services.imports.queries import ImportQueries


class ImportApplicationService(ImportAccess):
    def __init__(
        self,
        db: Session,
        settings: Settings,
        *,
        registry: ImportRegistry | None = None,
        storage: LocalImportStorage | None = None,
    ) -> None:
        super().__init__(db, settings, registry=registry, storage=storage)
        self.catalog = ImportCatalog(self)
        self.queries = ImportQueries(self)
        self.control = ImportControlPlane(self)

    def types(self, ctx: AdminContext, scope_type: str | None = None) -> dict[str, Any]:
        return self.catalog.types(ctx, scope_type)

    def template(self, ctx: AdminContext, type_key: str, version_no: int) -> dict[str, Any]:
        return self.catalog.template(ctx, type_key, version_no)

    def template_file(
        self, ctx: AdminContext, type_key: str, version_no: int, file_format: str = "xlsx"
    ) -> FileDownload:
        return self.catalog.template_file(ctx, type_key, version_no, file_format)

    def batches(self, ctx: AdminContext, **filters: Any) -> dict[str, Any]:
        return self.queries.batches(ctx, **filters)

    def batch(self, ctx: AdminContext, batch_id: str) -> dict[str, Any]:
        return self.queries.batch(ctx, batch_id)

    def rows(self, ctx: AdminContext, batch_id: str, **filters: Any) -> dict[str, Any]:
        return self.queries.rows(ctx, batch_id, **filters)

    def issues(self, ctx: AdminContext, batch_id: str, **filters: Any) -> dict[str, Any]:
        return self.queries.issues(ctx, batch_id, **filters)

    def events(self, ctx: AdminContext, batch_id: str, **filters: Any) -> dict[str, Any]:
        return self.queries.events(ctx, batch_id, **filters)

    def error_file(self, ctx: AdminContext, batch_id: str) -> dict[str, Any]:
        return self.queries.error_file(ctx, batch_id)

    def download_error_file(
        self, ctx: AdminContext, batch_id: str, generation: int, request_id: str
    ) -> FileDownload:
        return self.queries.download_error_file(ctx, batch_id, generation, request_id)

    def create(
        self, ctx: AdminContext, data: schema.ImportBatchCreate, *, key: str, request_id: str
    ) -> dict[str, Any]:
        return self.control.create(ctx, data, key=key, request_id=request_id)

    def upload(
        self,
        ctx: AdminContext,
        *,
        batch_id: str,
        key: str,
        request_id: str,
        file: BinaryIO,
        filename: str,
    ) -> dict[str, Any]:
        return self.control.upload(
            ctx, batch_id=batch_id, key=key, request_id=request_id, file=file, filename=filename
        )

    def mutate(
        self,
        ctx: AdminContext,
        batch_id: str,
        action: str,
        data: dict[str, Any],
        key: str,
        request_id: str,
    ) -> dict[str, Any]:
        return self.control.mutate(ctx, batch_id, action, data, key, request_id)
