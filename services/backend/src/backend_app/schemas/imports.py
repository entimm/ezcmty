"""Typed HTTP projections for the import contract."""

from typing import Annotated, Literal

from pydantic import AwareDatetime, ConfigDict, Field, WithJsonSchema, model_validator

from backend_app.core.identifiers import UUID_PATTERN
from backend_app.schemas.admin import AdminSchema, Identifier

ImportHash = Annotated[str, Field(min_length=64, max_length=64, pattern="^[0-9a-f]{64}$")]
ImportTypeKey = Annotated[str, Field(min_length=1, max_length=64, pattern="^[a-z][a-z0-9_]*$")]
ImportFieldKey = Annotated[str, Field(min_length=1, max_length=64, pattern="^[a-z][a-z0-9_]*$")]
ImportScalar = Annotated[
    str | int | float | bool | None,
    WithJsonSchema({"type": ["string", "integer", "number", "boolean", "null"]}),
]
ImportCreateMode = Annotated[
    Literal["create"], WithJsonSchema({"type": "string", "enum": ["create"]})
]
ImportBatchStatus = Literal[
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
ImportBatchPhase = Literal[
    "awaiting_source_file",
    "uploading",
    "parse_queued",
    "parse",
    "precheck_queued",
    "precheck",
    "awaiting_confirmation",
    "apply_queued",
    "apply",
    "recovery_queued",
    "recovery",
    "cancelling",
    "finished",
]
ImportTaskPhase = Literal["parse", "precheck", "apply", "artifact"]
ImportTaskStatus = Literal["ready", "running", "completed", "paused", "cancelled"]
ImportScopeType = Literal["company", "community"]
ImportExecutionStatus = Literal[
    "pending", "created", "skipped", "failed", "uncertain", "cancelled", "excluded"
]
ImportPrecheckStatus = Literal["pending", "valid", "warning", "error"]
ImportPlannedAction = Literal["none", "create", "skip", "conflict"]
ImportApplyPolicy = Literal["all_rows", "valid_rows_only"]
ImportFileFormat = Literal["csv", "xlsx"]
ImportErrorFileStatus = Literal[
    "not_generated", "queued", "generating", "ready", "stale", "failed", "expired"
]
ImportNextAction = Literal[
    "upload_source_file",
    "precheck",
    "confirm",
    "cancel",
    "retry_failed",
    "recover",
    "generate_error_file",
    "download_error_file",
]


class ImportVersion(AdminSchema):
    version_no: Annotated[int, Field(ge=1)]
    config_hash: ImportHash
    available_for_new_batches: bool
    template_downloadable: bool
    released_at: AwareDatetime
    release_notes: Annotated[str, Field(max_length=2000)]


class ImportType(AdminSchema):
    key: ImportTypeKey
    name: Annotated[str, Field(min_length=1, max_length=128)]
    allowed_scope_types: list[ImportScopeType]
    supported_modes: list[ImportCreateMode]
    versions: list[ImportVersion]


class ImportTypeList(AdminSchema):
    items: list[ImportType]


class ImportTemplateField(AdminSchema):
    key: ImportFieldKey
    label: Annotated[str, Field(min_length=1, max_length=128)]
    order: Annotated[int, Field(ge=1)]
    required: bool
    data_type: Literal["string", "integer", "decimal", "boolean", "date", "datetime"]
    max_length: Annotated[int, Field(ge=1)] | None
    format: Annotated[str, Field(min_length=1, max_length=128)] | None
    enum_values: list[ImportScalar]
    example: ImportScalar
    description: Annotated[str, Field(max_length=1000)]
    normalization_rules: list[Annotated[str, Field(min_length=1, max_length=500)]]


class ImportTemplate(AdminSchema):
    key: ImportTypeKey
    name: Annotated[str, Field(min_length=1, max_length=128)]
    version_no: Annotated[int, Field(ge=1)]
    config_hash: ImportHash
    available_for_new_batches: bool
    released_at: AwareDatetime
    release_notes: Annotated[str, Field(max_length=2000)]
    fields: list[ImportTemplateField]


class ImportScopeInput(AdminSchema):
    model_config = ConfigDict(strict=True)
    type: ImportScopeType
    id: Identifier


class ImportScope(AdminSchema):
    type: ImportScopeType
    id: Identifier
    name: Annotated[str, Field(min_length=1, max_length=128)]


class ImportTemplateIdentity(AdminSchema):
    key: ImportTypeKey
    version_no: Annotated[int, Field(ge=1)]
    config_hash: ImportHash


class ImportTaskIdentity(AdminSchema):
    id: Identifier
    phase: ImportTaskPhase
    status: ImportTaskStatus


class ImportTaskProgress(AdminSchema):
    id: Identifier
    phase: ImportTaskPhase
    status: ImportTaskStatus
    progress_done: Annotated[int, Field(ge=0)]
    progress_total: Annotated[int, Field(ge=0)] | None
    updated_at: AwareDatetime
    last_error_code: Annotated[str, Field(min_length=1, max_length=128)] | None


class ImportSourceIdentity(AdminSchema):
    id: Identifier
    size_bytes: Annotated[int, Field(ge=0, le=10485760)]
    sha256: ImportHash


class ImportSourceArtifact(AdminSchema):
    id: Identifier
    file_name: Annotated[str, Field(min_length=1, max_length=255)] | None
    media_type: Literal[
        "text/csv", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    ]
    size_bytes: Annotated[int, Field(ge=0, le=10485760)]
    sha256: ImportHash
    expires_at: AwareDatetime
    available: bool


class ImportPreview(AdminSchema):
    model_config = ConfigDict(json_schema_extra={"x-preview-ttl-hours": 24})
    version: Annotated[int, Field(ge=1)]
    fingerprint: ImportHash
    generated_at: AwareDatetime
    expires_at: AwareDatetime


class ImportPreviewStatistics(AdminSchema):
    create_rows: Annotated[int, Field(ge=0)]
    update_rows: Annotated[int, Field(ge=0)]
    skip_rows: Annotated[int, Field(ge=0)]
    warning_rows: Annotated[int, Field(ge=0)]
    error_rows: Annotated[int, Field(ge=0)]


class ImportExecutionStatistics(AdminSchema):
    created_rows: Annotated[int, Field(ge=0)]
    updated_rows: Annotated[int, Field(ge=0)]
    skipped_rows: Annotated[int, Field(ge=0)]
    failed_rows: Annotated[int, Field(ge=0)]
    uncertain_rows: Annotated[int, Field(ge=0)]
    cancelled_rows: Annotated[int, Field(ge=0)]
    excluded_rows: Annotated[int, Field(ge=0)]
    processed_rows: Annotated[int, Field(ge=0)]
    retryable_failed_rows: Annotated[int, Field(ge=0)]


class ImportStatistics(AdminSchema):
    total_rows: Annotated[int, Field(ge=0)]
    preview: ImportPreviewStatistics
    execution: ImportExecutionStatistics


class ImportActor(AdminSchema):
    id: Identifier
    name: Annotated[str, Field(min_length=1, max_length=128)]


class ImportBusinessField(AdminSchema):
    key: ImportFieldKey
    label: Annotated[str, Field(min_length=1, max_length=128)]
    format: Literal["text", "money_cents"]


class ImportBusinessSummary(AdminSchema):
    key: ImportFieldKey
    label: Annotated[str, Field(min_length=1, max_length=128)]
    format: Literal["integer", "money_cents"]
    without_warning_rows: Annotated[str, Field(pattern="^(0|[1-9][0-9]*)$")]
    with_warning_rows: Annotated[str, Field(pattern="^(0|[1-9][0-9]*)$")]


class ImportBusinessPreview(AdminSchema):
    fields: list[ImportBusinessField]
    summary: list[ImportBusinessSummary]


class ImportBatch(AdminSchema):
    template_fields: list[ImportTemplateField]
    model_config = ConfigDict(json_schema_extra={"x-sensitive-retention-days": 30})
    id: Identifier
    parent_batch_id: Identifier | None
    import_type: ImportTypeKey
    import_type_name: Annotated[str, Field(min_length=1, max_length=128)]
    property_company_id: Identifier
    template: ImportTemplateIdentity
    scope: ImportScope
    mode: ImportCreateMode
    status: ImportBatchStatus
    phase: ImportBatchPhase
    last_error_code: Annotated[str, Field(min_length=1, max_length=128)] | None
    blocked_reason: Annotated[str, Field(min_length=1, max_length=1000)] | None
    preview: ImportPreview | None
    apply_policy: ImportApplyPolicy | None
    include_warning_rows: bool | None
    statistics: ImportStatistics
    source_artifact: ImportSourceArtifact | None
    active_task: ImportTaskProgress | None
    created_by: ImportActor
    created_at: AwareDatetime
    updated_at: AwareDatetime
    retention_until: AwareDatetime
    confirmed_at: AwareDatetime | None
    started_at: AwareDatetime | None
    finished_at: AwareDatetime | None
    next_actions: list[ImportNextAction]
    business_preview: ImportBusinessPreview | None = None


class ImportBatchAction(AdminSchema):
    batch_id: Identifier
    status: ImportBatchStatus
    phase: ImportBatchPhase
    preview_version: Annotated[int, Field(ge=0)]
    active_task: ImportTaskIdentity | None
    source_artifact: ImportSourceIdentity | None


class ImportBatchCreate(AdminSchema):
    model_config = ConfigDict(strict=True)
    import_type: ImportTypeKey
    template_version_no: Annotated[int, Field(ge=1)]
    property_company_id: Annotated[
        Identifier | None,
        WithJsonSchema(
            {
                "type": "string",
                "format": "uuid",
                "minLength": 36,
                "maxLength": 36,
                "pattern": UUID_PATTERN,
            }
        ),
    ] = None

    @model_validator(mode="after")
    def company_cannot_be_null(self) -> ImportBatchCreate:
        if "property_company_id" in self.model_fields_set and self.property_company_id is None:
            raise ValueError("Property company cannot be null")
        return self

    scope: ImportScopeInput
    mode: ImportCreateMode


class ImportPrecheck(AdminSchema):
    model_config = ConfigDict(strict=True)
    preview_version: Annotated[int, Field(ge=0)]


class ImportConfirm(AdminSchema):
    model_config = ConfigDict(strict=True)
    preview_version: Annotated[int, Field(ge=1)]
    preview_fingerprint: ImportHash
    apply_policy: ImportApplyPolicy
    include_warning_rows: bool


class ImportRetry(AdminSchema):
    model_config = ConfigDict(strict=True)
    selection: Annotated[
        Literal["retryable_only"], WithJsonSchema({"type": "string", "enum": ["retryable_only"]})
    ]


class ImportRetryResult(AdminSchema):
    source_batch_id: Identifier
    selected_rows: Annotated[int, Field(ge=1)]
    batch: ImportBatchAction


class ImportRecover(AdminSchema):
    model_config = ConfigDict(strict=True)
    reason: Annotated[str, Field(min_length=1, max_length=500)]


class ImportErrorFileCreate(AdminSchema):
    model_config = ConfigDict(strict=True)
    format: ImportFileFormat
    preview_version: Annotated[int, Field(ge=1)]


class ImportErrorFileAction(AdminSchema):
    batch_id: Identifier
    status: ImportErrorFileStatus
    generation: Annotated[int, Field(ge=1)]
    source_preview_version: Annotated[int, Field(ge=1)]
    task: ImportTaskIdentity


class ImportErrorFile(AdminSchema):
    batch_id: Identifier
    status: ImportErrorFileStatus
    generation: Annotated[int, Field(ge=1)] | None
    source_preview_version: Annotated[int, Field(ge=1)] | None
    format: ImportFileFormat | None
    task: ImportTaskProgress | None
    file_name: Annotated[str, Field(min_length=1, max_length=255)] | None
    media_type: (
        Literal["text/csv", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"]
        | None
    )
    size_bytes: Annotated[int, Field(ge=0)] | None
    sha256: ImportHash | None
    generated_at: AwareDatetime | None
    expires_at: AwareDatetime | None
    last_error_code: Annotated[str, Field(min_length=1, max_length=128)] | None
    downloadable: bool


ImportValues = dict[str, ImportScalar]
ImportBusinessValues = dict[str, ImportScalar]


class ImportRow(AdminSchema):
    id: Identifier
    row_no: Annotated[int, Field(ge=1)]
    precheck_status: ImportPrecheckStatus
    planned_action: ImportPlannedAction
    raw_values: ImportValues
    normalized_values: ImportValues | None
    issue_count: Annotated[int, Field(ge=0)]
    execution_status: ImportExecutionStatus
    result_code: Annotated[str, Field(min_length=1, max_length=128)] | None
    result_message: Annotated[str, Field(min_length=1, max_length=1000)] | None
    result_at: AwareDatetime | None
    business_values: ImportBusinessValues | None = None


class ImportIssue(AdminSchema):
    id: Identifier
    preview_version: Annotated[int, Field(ge=0)]
    phase: Literal["parse", "precheck", "apply"]
    row_no: Annotated[int, Field(ge=1)] | None
    column_index: Annotated[int, Field(ge=1)] | None
    column_name: Annotated[str, Field(min_length=1, max_length=128)] | None
    field_key: ImportFieldKey | None
    cell_reference: Annotated[str, Field(min_length=1, max_length=32)] | None
    severity: Literal["warning", "error"]
    code: Annotated[str, Field(min_length=1, max_length=128)]
    message: Annotated[str, Field(min_length=1, max_length=1000)]
    suggestion: Annotated[str, Field(min_length=1, max_length=1000)] | None
    raw_value: ImportScalar
    normalized_value: ImportScalar
    retryable: bool


class ImportEvent(AdminSchema):
    id: Identifier
    event_type: Annotated[str, Field(min_length=1, max_length=64)]
    phase: ImportTaskPhase | None
    message: Annotated[str, Field(min_length=1, max_length=1000)]
    created_at: AwareDatetime


class ImportBatchPage(AdminSchema):
    items: list[ImportBatch]
    total: Annotated[int, Field(ge=0)]
    page: Annotated[int, Field(ge=1)]
    page_size: Annotated[int, Field(ge=1, le=100)]


class ImportRowPage(AdminSchema):
    items: list[ImportRow]
    total: Annotated[int, Field(ge=0)]
    page: Annotated[int, Field(ge=1)]
    page_size: Annotated[int, Field(ge=1, le=100)]


class ImportIssuePage(AdminSchema):
    items: list[ImportIssue]
    total: Annotated[int, Field(ge=0)]
    page: Annotated[int, Field(ge=1)]
    page_size: Annotated[int, Field(ge=1, le=100)]


class ImportEventPage(AdminSchema):
    items: list[ImportEvent]
    total: Annotated[int, Field(ge=0)]
    page: Annotated[int, Field(ge=1)]
    page_size: Annotated[int, Field(ge=1, le=100)]
