"""HTTP assembly for each independently authenticated import entry point."""

from collections.abc import Callable
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Header, Path, Query, Request, Response, UploadFile
from fastapi.params import Depends as DependsParameter
from pydantic import AwareDatetime, WithJsonSchema
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from backend_app.api.import_headers import file_response, import_responses
from backend_app.api.payment_headers import no_store
from backend_app.core.config import get_settings
from backend_app.core.errors import AppError
from backend_app.core.identifiers import UUID_PATTERN
from backend_app.db.session import get_database_session
from backend_app.schemas import imports as schema
from backend_app.schemas.admin import Identifier
from backend_app.services.contracts.admin import AdminContext
from backend_app.services.platform_admin.imports import PlatformImportService
from backend_app.services.property_admin.imports import PropertyImportService


def create_import_router(
    scope: Literal["platform_admin", "property_admin"],
    permission: Callable[[str], DependsParameter],
    check_write: Callable[..., None],
) -> APIRouter:
    router = APIRouter(tags=["imports"], dependencies=[Depends(no_store)])
    prefix = "platform" if scope == "platform_admin" else "property"

    def service(
        db: Annotated[Session, Depends(get_database_session)],
    ) -> PlatformImportService | PropertyImportService:
        cls = PlatformImportService if scope == "platform_admin" else PropertyImportService
        return cls(db, get_settings())

    Service = Annotated[PlatformImportService | PropertyImportService, Depends(service)]

    @router.get(
        "/v1/import-types",
        operation_id="listImportTypes",
        response_model=schema.ImportTypeList,
        responses=import_responses(200, 401, 403, 404, 422, 500, 503),
    )
    def listImportTypes(
        svc: Service,
        ctx: Annotated[AdminContext, permission(prefix + ".import.create")],
        scope_type: Annotated[
            Literal["company", "community"] | None,
            Query(),
            WithJsonSchema({"type": "string", "enum": ["company", "community"]}),
        ] = None,
    ) -> schema.ImportTypeList:
        return schema.ImportTypeList.model_validate(svc.types(ctx, scope_type=scope_type))

    @router.get(
        "/v1/import-types/{type_key}/versions/{version_no}",
        operation_id="getImportTemplate",
        response_model=schema.ImportTemplate,
        responses=import_responses(200, 401, 403, 404, 409, 422, 500, 503),
    )
    def getImportTemplate(
        svc: Service,
        ctx: Annotated[AdminContext, permission(prefix + ".import.create")],
        type_key: Annotated[str, Path(min_length=1, max_length=64, pattern="^[a-z][a-z0-9_]*$")],
        version_no: Annotated[int, Path(ge=1)],
    ) -> schema.ImportTemplate:
        return schema.ImportTemplate.model_validate(
            svc.template(ctx, type_key=type_key, version_no=version_no)
        )

    @router.get(
        "/v1/import-types/{type_key}/versions/{version_no}/template-file",
        operation_id="downloadImportTemplate",
        response_class=Response,
        responses=import_responses(200, 401, 403, 404, 409, 422, 500, 503, download=True),
    )
    def downloadImportTemplate(
        svc: Service,
        ctx: Annotated[AdminContext, permission(prefix + ".import.create")],
        type_key: Annotated[str, Path(min_length=1, max_length=64, pattern="^[a-z][a-z0-9_]*$")],
        version_no: Annotated[int, Path(ge=1)],
        file_format: Annotated[
            Literal["csv", "xlsx"] | None,
            Query(alias="format"),
            WithJsonSchema({"type": "string", "enum": ["csv", "xlsx"], "default": "xlsx"}),
        ] = "xlsx",
    ) -> Response:
        return file_response(
            svc.template_file(
                ctx, type_key=type_key, version_no=version_no, file_format=file_format or "xlsx"
            )
        )

    @router.post(
        "/v1/import-batches",
        operation_id="createImportBatch",
        response_model=schema.ImportBatchAction,
        status_code=201,
        dependencies=[Depends(check_write)],
        responses=import_responses(201, 401, 403, 404, 409, 422, 429, 500, 503),
    )
    def createImportBatch(
        request: Request,
        data: schema.ImportBatchCreate,
        svc: Service,
        ctx: Annotated[AdminContext, permission(prefix + ".import.create")],
        key: Annotated[
            str,
            Header(
                min_length=1, max_length=128, pattern="^[A-Za-z0-9_-]+$", alias="Idempotency-Key"
            ),
        ],
    ) -> schema.ImportBatchAction:
        return schema.ImportBatchAction.model_validate(
            svc.create(ctx, data, key=key, request_id=request.state.request_id)
        )

    @router.get(
        "/v1/import-batches",
        operation_id="listImportBatches",
        response_model=schema.ImportBatchPage,
        responses=import_responses(200, 401, 403, 404, 422, 500, 503),
    )
    def listImportBatches(
        svc: Service,
        ctx: Annotated[AdminContext, permission(prefix + ".import.read")],
        page: Annotated[
            int | None, Query(ge=1), WithJsonSchema({"type": "integer", "minimum": 1, "default": 1})
        ] = 1,
        page_size: Annotated[
            int | None,
            Query(ge=1, le=100),
            WithJsonSchema({"type": "integer", "minimum": 1, "maximum": 100, "default": 20}),
        ] = 20,
        property_company_id: Annotated[
            Identifier | None,
            Query(
                min_length=36,
                max_length=36,
                pattern=UUID_PATTERN,
            ),
            WithJsonSchema(
                {
                    "type": "string",
                    "format": "uuid",
                    "minLength": 36,
                    "maxLength": 36,
                    "pattern": UUID_PATTERN,
                    "description": "带连字符的 UUIDv4 或 UUIDv7；响应统一使用小写标准形式。",
                }
            ),
        ] = None,
        import_type: Annotated[
            str | None,
            Query(min_length=1, max_length=64, pattern="^[a-z][a-z0-9_]*$"),
            WithJsonSchema(
                {"type": "string", "pattern": "^[a-z][a-z0-9_]*$", "minLength": 1, "maxLength": 64}
            ),
        ] = None,
        scope_type: Annotated[
            Literal["company", "community"] | None,
            Query(),
            WithJsonSchema({"type": "string", "enum": ["company", "community"]}),
        ] = None,
        scope_id: Annotated[
            Identifier | None,
            Query(
                min_length=36,
                max_length=36,
                pattern=UUID_PATTERN,
            ),
            WithJsonSchema(
                {
                    "type": "string",
                    "format": "uuid",
                    "minLength": 36,
                    "maxLength": 36,
                    "pattern": UUID_PATTERN,
                    "description": "带连字符的 UUIDv4 或 UUIDv7；响应统一使用小写标准形式。",
                }
            ),
        ] = None,
        status: Annotated[
            Literal[
                "draft",
                "uploading",
                "prechecking",
                "preview_ready",
                "executing",
                "completed",
                "partial_failed",
                "failed",
                "blocked",
                "cancel_requested",
                "cancelled",
                "expired",
            ]
            | None,
            Query(),
            WithJsonSchema(
                {
                    "type": "string",
                    "enum": [
                        "draft",
                        "uploading",
                        "prechecking",
                        "preview_ready",
                        "executing",
                        "completed",
                        "partial_failed",
                        "failed",
                        "blocked",
                        "cancel_requested",
                        "cancelled",
                        "expired",
                    ],
                }
            ),
        ] = None,
        created_by: Annotated[
            Identifier | None,
            Query(
                min_length=36,
                max_length=36,
                pattern=UUID_PATTERN,
            ),
            WithJsonSchema(
                {
                    "type": "string",
                    "format": "uuid",
                    "minLength": 36,
                    "maxLength": 36,
                    "pattern": UUID_PATTERN,
                    "description": "带连字符的 UUIDv4 或 UUIDv7；响应统一使用小写标准形式。",
                }
            ),
        ] = None,
        has_errors: Annotated[bool | None, Query(), WithJsonSchema({"type": "boolean"})] = None,
        created_from: Annotated[
            AwareDatetime | None,
            Query(),
            WithJsonSchema(
                {
                    "type": "string",
                    "format": "date-time",
                    "description": "带时区 RFC 3339；响应为 UTC Z。",
                }
            ),
        ] = None,
        created_before: Annotated[
            AwareDatetime | None,
            Query(),
            WithJsonSchema(
                {
                    "type": "string",
                    "format": "date-time",
                    "description": "带时区 RFC 3339；响应为 UTC Z。",
                }
            ),
        ] = None,
        sort: Annotated[
            Literal["created_at,id", "-created_at,-id", "updated_at,id", "-updated_at,-id"] | None,
            Query(),
            WithJsonSchema(
                {
                    "type": "string",
                    "enum": [
                        "created_at,id",
                        "-created_at,-id",
                        "updated_at,id",
                        "-updated_at,-id",
                    ],
                    "default": "-created_at,-id",
                }
            ),
        ] = "-created_at,-id",
    ) -> schema.ImportBatchPage:
        return schema.ImportBatchPage.model_validate(
            svc.batches(
                ctx,
                page=page,
                page_size=page_size,
                property_company_id=property_company_id,
                import_type=import_type,
                scope_type=scope_type,
                scope_id=scope_id,
                status=status,
                created_by=created_by,
                has_errors=has_errors,
                created_from=created_from,
                created_before=created_before,
                sort=sort,
            )
        )

    @router.get(
        "/v1/import-batches/{batch_id}",
        operation_id="getImportBatch",
        response_model=schema.ImportBatch,
        responses=import_responses(200, 401, 403, 404, 422, 500, 503),
    )
    def getImportBatch(
        svc: Service,
        ctx: Annotated[AdminContext, permission(prefix + ".import.read")],
        batch_id: Annotated[
            Identifier,
            Path(
                min_length=36,
                max_length=36,
                pattern=UUID_PATTERN,
                json_schema_extra={"format": "uuid"},
            ),
        ],
    ) -> schema.ImportBatch:
        return schema.ImportBatch.model_validate(svc.batch(ctx, batch_id=batch_id))

    @router.post(
        "/v1/import-batches/{batch_id}/source-file",
        operation_id="uploadImportSourceFile",
        openapi_extra={
            "requestBody": {
                "content": {
                    "multipart/form-data": {
                        "encoding": {
                            "file": {
                                "contentType": (
                                    "text/csv, "
                                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                                )
                            }
                        },
                        "schema": {"additionalProperties": False},
                    }
                }
            }
        },
        response_model=schema.ImportBatchAction,
        status_code=202,
        dependencies=[Depends(check_write)],
        responses=import_responses(202, 401, 403, 404, 409, 410, 413, 415, 422, 429, 500, 503),
    )
    async def uploadImportSourceFile(
        request: Request,
        file: Annotated[
            UploadFile,
            File(json_schema_extra={"format": "binary", "maxLength": 10485760}),
            WithJsonSchema({"type": "string", "format": "binary", "maxLength": 10485760}),
        ],
        svc: Service,
        ctx: Annotated[AdminContext, permission(prefix + ".import.upload")],
        batch_id: Annotated[
            Identifier,
            Path(
                min_length=36,
                max_length=36,
                pattern=UUID_PATTERN,
                json_schema_extra={"format": "uuid"},
            ),
        ],
        key: Annotated[
            str,
            Header(
                min_length=1, max_length=128, pattern="^[A-Za-z0-9_-]+$", alias="Idempotency-Key"
            ),
        ],
    ) -> schema.ImportBatchAction:
        form = await request.form()
        if list(form.keys()) != ["file"] or len(form.getlist("file")) != 1:
            raise AppError("VALIDATION_ERROR")
        return schema.ImportBatchAction.model_validate(
            await run_in_threadpool(
                svc.upload,
                ctx,
                batch_id=batch_id,
                key=key,
                request_id=request.state.request_id,
                file=file.file,
                filename=file.filename or "upload",
            )
        )

    @router.get(
        "/v1/import-batches/{batch_id}/rows",
        operation_id="listImportRows",
        response_model=schema.ImportRowPage,
        responses=import_responses(200, 401, 403, 404, 409, 410, 422, 500, 503),
    )
    def listImportRows(
        svc: Service,
        ctx: Annotated[AdminContext, permission(prefix + ".import.read")],
        batch_id: Annotated[
            Identifier,
            Path(
                min_length=36,
                max_length=36,
                pattern=UUID_PATTERN,
                json_schema_extra={"format": "uuid"},
            ),
        ],
        page: Annotated[
            int | None, Query(ge=1), WithJsonSchema({"type": "integer", "minimum": 1, "default": 1})
        ] = 1,
        page_size: Annotated[
            int | None,
            Query(ge=1, le=100),
            WithJsonSchema({"type": "integer", "minimum": 1, "maximum": 100, "default": 20}),
        ] = 20,
        precheck_status: Annotated[
            Literal["pending", "valid", "warning", "error"] | None,
            Query(),
            WithJsonSchema({"type": "string", "enum": ["pending", "valid", "warning", "error"]}),
        ] = None,
        execution_status: Annotated[
            Literal["pending", "created", "skipped", "failed", "uncertain", "cancelled", "excluded"]
            | None,
            Query(),
            WithJsonSchema(
                {
                    "type": "string",
                    "enum": [
                        "pending",
                        "created",
                        "skipped",
                        "failed",
                        "uncertain",
                        "cancelled",
                        "excluded",
                    ],
                }
            ),
        ] = None,
        planned_action: Annotated[
            Literal["none", "create", "skip", "conflict"] | None,
            Query(),
            WithJsonSchema({"type": "string", "enum": ["none", "create", "skip", "conflict"]}),
        ] = None,
        row_no: Annotated[
            int | None, Query(ge=1), WithJsonSchema({"type": "integer", "minimum": 1})
        ] = None,
        field_key: Annotated[
            str | None,
            Query(min_length=1, max_length=64, pattern="^[a-z][a-z0-9_]*$"),
            WithJsonSchema(
                {"type": "string", "pattern": "^[a-z][a-z0-9_]*$", "minLength": 1, "maxLength": 64}
            ),
        ] = None,
    ) -> schema.ImportRowPage:
        return schema.ImportRowPage.model_validate(
            svc.rows(
                ctx,
                batch_id=batch_id,
                page=page,
                page_size=page_size,
                precheck_status=precheck_status,
                execution_status=execution_status,
                planned_action=planned_action,
                row_no=row_no,
                field_key=field_key,
            )
        )

    @router.get(
        "/v1/import-batches/{batch_id}/issues",
        operation_id="listImportIssues",
        response_model=schema.ImportIssuePage,
        responses=import_responses(200, 401, 403, 404, 409, 410, 422, 500, 503),
    )
    def listImportIssues(
        svc: Service,
        ctx: Annotated[AdminContext, permission(prefix + ".import.read")],
        batch_id: Annotated[
            Identifier,
            Path(
                min_length=36,
                max_length=36,
                pattern=UUID_PATTERN,
                json_schema_extra={"format": "uuid"},
            ),
        ],
        page: Annotated[
            int | None, Query(ge=1), WithJsonSchema({"type": "integer", "minimum": 1, "default": 1})
        ] = 1,
        page_size: Annotated[
            int | None,
            Query(ge=1, le=100),
            WithJsonSchema({"type": "integer", "minimum": 1, "maximum": 100, "default": 20}),
        ] = 20,
        severity: Annotated[
            Literal["warning", "error"] | None,
            Query(),
            WithJsonSchema({"type": "string", "enum": ["warning", "error"]}),
        ] = None,
        phase: Annotated[
            Literal["parse", "precheck", "apply"] | None,
            Query(),
            WithJsonSchema({"type": "string", "enum": ["parse", "precheck", "apply"]}),
        ] = None,
        row_no: Annotated[
            int | None, Query(ge=1), WithJsonSchema({"type": "integer", "minimum": 1})
        ] = None,
        field_key: Annotated[
            str | None,
            Query(min_length=1, max_length=64, pattern="^[a-z][a-z0-9_]*$"),
            WithJsonSchema(
                {"type": "string", "pattern": "^[a-z][a-z0-9_]*$", "minLength": 1, "maxLength": 64}
            ),
        ] = None,
        code: Annotated[
            str | None,
            Query(min_length=1, max_length=128),
            WithJsonSchema({"type": "string", "minLength": 1, "maxLength": 128}),
        ] = None,
        retryable: Annotated[bool | None, Query(), WithJsonSchema({"type": "boolean"})] = None,
    ) -> schema.ImportIssuePage:
        return schema.ImportIssuePage.model_validate(
            svc.issues(
                ctx,
                batch_id=batch_id,
                page=page,
                page_size=page_size,
                severity=severity,
                phase=phase,
                row_no=row_no,
                field_key=field_key,
                code=code,
                retryable=retryable,
            )
        )

    @router.get(
        "/v1/import-batches/{batch_id}/events",
        operation_id="listImportEvents",
        response_model=schema.ImportEventPage,
        responses=import_responses(200, 401, 403, 404, 422, 500, 503),
    )
    def listImportEvents(
        svc: Service,
        ctx: Annotated[AdminContext, permission(prefix + ".import.read")],
        batch_id: Annotated[
            Identifier,
            Path(
                min_length=36,
                max_length=36,
                pattern=UUID_PATTERN,
                json_schema_extra={"format": "uuid"},
            ),
        ],
        page: Annotated[
            int | None, Query(ge=1), WithJsonSchema({"type": "integer", "minimum": 1, "default": 1})
        ] = 1,
        page_size: Annotated[
            int | None,
            Query(ge=1, le=100),
            WithJsonSchema({"type": "integer", "minimum": 1, "maximum": 100, "default": 20}),
        ] = 20,
        sort: Annotated[
            Literal["created_at,id", "-created_at,-id"] | None,
            Query(),
            WithJsonSchema(
                {
                    "type": "string",
                    "enum": ["created_at,id", "-created_at,-id"],
                    "default": "created_at,id",
                }
            ),
        ] = "created_at,id",
    ) -> schema.ImportEventPage:
        return schema.ImportEventPage.model_validate(
            svc.events(ctx, batch_id=batch_id, page=page, page_size=page_size, sort=sort)
        )

    @router.post(
        "/v1/import-batches/{batch_id}/precheck",
        operation_id="precheckImportBatch",
        response_model=schema.ImportBatchAction,
        status_code=202,
        dependencies=[Depends(check_write)],
        responses=import_responses(202, 401, 403, 404, 409, 410, 422, 429, 500, 503),
    )
    def precheckImportBatch(
        request: Request,
        data: schema.ImportPrecheck,
        svc: Service,
        ctx: Annotated[AdminContext, permission(prefix + ".import.precheck")],
        batch_id: Annotated[
            Identifier,
            Path(
                min_length=36,
                max_length=36,
                pattern=UUID_PATTERN,
                json_schema_extra={"format": "uuid"},
            ),
        ],
        key: Annotated[
            str,
            Header(
                min_length=1, max_length=128, pattern="^[A-Za-z0-9_-]+$", alias="Idempotency-Key"
            ),
        ],
    ) -> schema.ImportBatchAction:
        return schema.ImportBatchAction.model_validate(
            svc.mutate(
                ctx,
                batch_id,
                "precheck",
                data.model_dump(mode="json"),
                key,
                request.state.request_id,
            )
        )

    @router.post(
        "/v1/import-batches/{batch_id}/confirm",
        operation_id="confirmImportBatch",
        response_model=schema.ImportBatchAction,
        status_code=202,
        dependencies=[Depends(check_write)],
        responses=import_responses(202, 401, 403, 404, 409, 410, 422, 429, 500, 503),
    )
    def confirmImportBatch(
        request: Request,
        data: schema.ImportConfirm,
        svc: Service,
        ctx: Annotated[AdminContext, permission(prefix + ".import.execute")],
        batch_id: Annotated[
            Identifier,
            Path(
                min_length=36,
                max_length=36,
                pattern=UUID_PATTERN,
                json_schema_extra={"format": "uuid"},
            ),
        ],
        key: Annotated[
            str,
            Header(
                min_length=1, max_length=128, pattern="^[A-Za-z0-9_-]+$", alias="Idempotency-Key"
            ),
        ],
    ) -> schema.ImportBatchAction:
        return schema.ImportBatchAction.model_validate(
            svc.mutate(
                ctx,
                batch_id,
                "confirm",
                data.model_dump(mode="json"),
                key,
                request.state.request_id,
            )
        )

    @router.post(
        "/v1/import-batches/{batch_id}/cancel",
        operation_id="cancelImportBatch",
        response_model=schema.ImportBatchAction,
        status_code=202,
        dependencies=[Depends(check_write)],
        responses=import_responses(202, 401, 403, 404, 409, 422, 429, 500, 503),
    )
    def cancelImportBatch(
        request: Request,
        svc: Service,
        ctx: Annotated[AdminContext, permission(prefix + ".import.cancel")],
        batch_id: Annotated[
            Identifier,
            Path(
                min_length=36,
                max_length=36,
                pattern=UUID_PATTERN,
                json_schema_extra={"format": "uuid"},
            ),
        ],
        key: Annotated[
            str,
            Header(
                min_length=1, max_length=128, pattern="^[A-Za-z0-9_-]+$", alias="Idempotency-Key"
            ),
        ],
    ) -> schema.ImportBatchAction:
        return schema.ImportBatchAction.model_validate(
            svc.mutate(ctx, batch_id, "cancel", {}, key, request.state.request_id)
        )

    @router.post(
        "/v1/import-batches/{batch_id}/retry-failed",
        operation_id="retryFailedImportRows",
        response_model=schema.ImportRetryResult,
        status_code=201,
        dependencies=[Depends(check_write)],
        responses=import_responses(201, 401, 403, 404, 409, 410, 422, 429, 500, 503),
    )
    def retryFailedImportRows(
        request: Request,
        data: schema.ImportRetry,
        svc: Service,
        ctx: Annotated[AdminContext, permission(prefix + ".import.retry")],
        batch_id: Annotated[
            Identifier,
            Path(
                min_length=36,
                max_length=36,
                pattern=UUID_PATTERN,
                json_schema_extra={"format": "uuid"},
            ),
        ],
        key: Annotated[
            str,
            Header(
                min_length=1, max_length=128, pattern="^[A-Za-z0-9_-]+$", alias="Idempotency-Key"
            ),
        ],
    ) -> schema.ImportRetryResult:
        return schema.ImportRetryResult.model_validate(
            svc.mutate(
                ctx,
                batch_id,
                "retry_failed",
                data.model_dump(mode="json"),
                key,
                request.state.request_id,
            )
        )

    @router.post(
        "/v1/import-batches/{batch_id}/recover",
        operation_id="recoverImportBatch",
        response_model=schema.ImportBatchAction,
        status_code=202,
        dependencies=[Depends(check_write)],
        responses=import_responses(202, 401, 403, 404, 409, 410, 422, 429, 500, 503),
    )
    def recoverImportBatch(
        request: Request,
        data: schema.ImportRecover,
        svc: Service,
        ctx: Annotated[AdminContext, permission(prefix + ".import.recover")],
        batch_id: Annotated[
            Identifier,
            Path(
                min_length=36,
                max_length=36,
                pattern=UUID_PATTERN,
                json_schema_extra={"format": "uuid"},
            ),
        ],
        key: Annotated[
            str,
            Header(
                min_length=1, max_length=128, pattern="^[A-Za-z0-9_-]+$", alias="Idempotency-Key"
            ),
        ],
    ) -> schema.ImportBatchAction:
        return schema.ImportBatchAction.model_validate(
            svc.mutate(
                ctx,
                batch_id,
                "recover",
                data.model_dump(mode="json"),
                key,
                request.state.request_id,
            )
        )

    @router.post(
        "/v1/import-batches/{batch_id}/error-file",
        operation_id="generateImportErrorFile",
        response_model=schema.ImportErrorFileAction,
        status_code=202,
        dependencies=[Depends(check_write)],
        responses=import_responses(202, 401, 403, 404, 409, 410, 422, 429, 500, 503),
    )
    def generateImportErrorFile(
        request: Request,
        data: schema.ImportErrorFileCreate,
        svc: Service,
        ctx: Annotated[AdminContext, permission(prefix + ".import.generate_error_file")],
        batch_id: Annotated[
            Identifier,
            Path(
                min_length=36,
                max_length=36,
                pattern=UUID_PATTERN,
                json_schema_extra={"format": "uuid"},
            ),
        ],
        key: Annotated[
            str,
            Header(
                min_length=1, max_length=128, pattern="^[A-Za-z0-9_-]+$", alias="Idempotency-Key"
            ),
        ],
    ) -> schema.ImportErrorFileAction:
        return schema.ImportErrorFileAction.model_validate(
            svc.mutate(
                ctx,
                batch_id,
                "error_file",
                data.model_dump(mode="json"),
                key,
                request.state.request_id,
            )
        )

    @router.get(
        "/v1/import-batches/{batch_id}/artifacts/error-file",
        operation_id="getImportErrorFile",
        response_model=schema.ImportErrorFile,
        responses=import_responses(200, 401, 403, 404, 422, 500, 503),
    )
    def getImportErrorFile(
        svc: Service,
        ctx: Annotated[AdminContext, permission(prefix + ".import.read")],
        batch_id: Annotated[
            Identifier,
            Path(
                min_length=36,
                max_length=36,
                pattern=UUID_PATTERN,
                json_schema_extra={"format": "uuid"},
            ),
        ],
    ) -> schema.ImportErrorFile:
        return schema.ImportErrorFile.model_validate(svc.error_file(ctx, batch_id=batch_id))

    @router.get(
        "/v1/import-batches/{batch_id}/artifacts/error-file/download",
        operation_id="downloadImportErrorFile",
        response_class=Response,
        responses=import_responses(200, 401, 403, 404, 409, 410, 422, 500, 503, download=True),
    )
    def downloadImportErrorFile(
        request: Request,
        svc: Service,
        ctx: Annotated[AdminContext, permission(prefix + ".import.download")],
        batch_id: Annotated[
            Identifier,
            Path(
                min_length=36,
                max_length=36,
                pattern=UUID_PATTERN,
                json_schema_extra={"format": "uuid"},
            ),
        ],
        generation: Annotated[int, Query(ge=1)],
    ) -> Response:
        return file_response(
            svc.download_error_file(
                ctx, batch_id=batch_id, generation=generation, request_id=request.state.request_id
            )
        )

    return router
