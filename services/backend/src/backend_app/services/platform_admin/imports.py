from backend_app.core.errors import AppError
from backend_app.services.contracts.admin import AdminContext
from backend_app.services.imports.application import ImportApplicationService


class PlatformImportService(ImportApplicationService):
    scope = "platform_admin"

    def company_id(
        self, ctx: AdminContext, requested: str | None, *, creating: bool = False
    ) -> str | None:
        if ctx.scope != "platform_admin":
            raise AppError("auth.forbidden")
        if creating and requested is None:
            raise AppError("VALIDATION_ERROR")
        return requested
