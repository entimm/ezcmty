from backend_app.core.errors import AppError
from backend_app.services.contracts.admin import AdminContext
from backend_app.services.imports.application import ImportApplicationService


class PropertyImportService(ImportApplicationService):
    scope = "property_admin"

    def company_id(
        self, ctx: AdminContext, requested: str | None, *, creating: bool = False
    ) -> str:
        if ctx.scope != "property_admin" or ctx.property_company_id is None:
            raise AppError("auth.forbidden")
        if requested is not None:
            raise AppError("VALIDATION_ERROR")
        return ctx.property_company_id
