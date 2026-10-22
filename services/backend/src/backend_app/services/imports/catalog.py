import csv
import io
from dataclasses import asdict
from typing import Any

from backend_app.core.errors import AppError
from backend_app.integrations.import_files.storage import (
    safe_csv_cell,
)
from backend_app.services.contracts.admin import AdminContext
from backend_app.services.imports.access import ImportAccess
from backend_app.services.imports.artifacts import FileDownload


class ImportCatalog:
    def __init__(self, access: ImportAccess) -> None:
        self.access = access

    def types(self, ctx: AdminContext, scope_type: str | None = None) -> dict[str, Any]:
        _, _, permissions = self.access.authorize(ctx, "create")
        grouped: dict[str, dict[str, Any]] = {}
        for definition in self.access.registry.list():
            if (
                self.access.scope not in definition.allowed_actor_scopes
                or not set(definition.required_permissions) <= permissions
                or (not definition.available_for_new_batches)
            ):
                continue
            if scope_type and scope_type not in definition.allowed_scope_types:
                continue
            item = grouped.setdefault(
                definition.key,
                dict(
                    key=definition.key,
                    name=definition.name,
                    allowed_scope_types=list(definition.allowed_scope_types),
                    supported_modes=["create"],
                    versions=[],
                ),
            )
            item["versions"].append(
                dict(
                    version_no=definition.version_no,
                    config_hash=definition.config_hash,
                    available_for_new_batches=definition.available_for_new_batches,
                    template_downloadable=definition.template_downloadable,
                    released_at=definition.released_at,
                    release_notes=definition.release_notes,
                )
            )
        return {"items": list(grouped.values())}

    def template(self, ctx: AdminContext, type_key: str, version_no: int) -> dict[str, Any]:
        _, _, permissions = self.access.authorize(ctx, "create")
        definition = self.access.definition(
            type_key, version_no, permissions, missing_not_found=True
        )
        return dict(
            key=definition.key,
            name=definition.name,
            version_no=definition.version_no,
            config_hash=definition.config_hash,
            available_for_new_batches=definition.available_for_new_batches,
            released_at=definition.released_at,
            release_notes=definition.release_notes,
            fields=[
                {k: v for k, v in asdict(f).items() if k != "sensitive"} for f in definition.fields
            ],
        )

    def template_file(
        self, ctx: AdminContext, type_key: str, version_no: int, file_format: str = "xlsx"
    ) -> FileDownload:
        template = self.template(ctx, type_key, version_no)
        definition = self.access.registry.get(type_key, version_no)
        if not definition.template_downloadable:
            raise AppError("import.template_unavailable")
        self.access.db.rollback()
        output = io.BytesIO()
        if file_format == "csv":
            text = io.StringIO(newline="")
            writer = csv.writer(text)
            writer.writerow([safe_csv_cell(f["label"]) for f in template["fields"]])
            output.write(text.getvalue().encode("utf-8-sig"))
            media = "text/csv"
        else:
            from openpyxl import Workbook

            workbook = Workbook(write_only=True)
            sheet = workbook.create_sheet(definition.sheet_name)
            sheet.append([safe_csv_cell(f["label"]) for f in template["fields"]])
            workbook.save(output)
            workbook.close()
            media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        size = output.tell()
        output.seek(0)
        return FileDownload(output, f"import-{type_key}-v{version_no}.{file_format}", media, size)
