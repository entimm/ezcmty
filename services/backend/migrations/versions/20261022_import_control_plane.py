"""Add the generic import control plane and durable recovery evidence."""

import sqlalchemy as sa
from alembic import op

revision = "20261022_imports"
down_revision = "20261019_bill_payments"
branch_labels = None
depends_on = None

TABLES = (
    "import_batches",
    "import_requests",
    "import_artifacts",
    "import_operations",
    "import_rows",
    "import_issues",
    "import_tasks",
    "import_batch_events",
)


def upgrade() -> None:
    op.execute("""
CREATE TABLE import_batches (
id UUID NOT NULL,
property_company_id UUID NOT NULL,
community_id UUID,
scope_type VARCHAR(16) NOT NULL,
scope_snapshot JSONB NOT NULL,
template_key VARCHAR(64) NOT NULL,
template_version_no INTEGER NOT NULL,
template_config_hash CHAR(64) NOT NULL,
mode VARCHAR(16) DEFAULT 'create' NOT NULL,
apply_policy VARCHAR(24),
include_warning_rows BOOLEAN,
parent_batch_id UUID,
created_by_scope VARCHAR(32) NOT NULL,
created_by_id UUID NOT NULL,
request_id VARCHAR(64) NOT NULL,
status VARCHAR(24) DEFAULT 'draft' NOT NULL,
preview_version BIGINT DEFAULT '0' NOT NULL,
preview_fingerprint CHAR(64),
total_rows BIGINT DEFAULT '0' NOT NULL,
planned_create_rows BIGINT DEFAULT '0' NOT NULL,
planned_update_rows BIGINT DEFAULT '0' NOT NULL,
planned_skip_rows BIGINT DEFAULT '0' NOT NULL,
warning_rows BIGINT DEFAULT '0' NOT NULL,
error_rows BIGINT DEFAULT '0' NOT NULL,
created_rows BIGINT DEFAULT '0' NOT NULL,
updated_rows BIGINT DEFAULT '0' NOT NULL,
skipped_rows BIGINT DEFAULT '0' NOT NULL,
failed_rows BIGINT DEFAULT '0' NOT NULL,
uncertain_rows BIGINT DEFAULT '0' NOT NULL,
cancelled_rows BIGINT DEFAULT '0' NOT NULL,
processed_rows BIGINT DEFAULT '0' NOT NULL,
row_version BIGINT DEFAULT '1' NOT NULL,
last_error_code VARCHAR(128),
preview_expires_at TIMESTAMP(6) WITH TIME ZONE,
cancel_requested_at TIMESTAMP(6) WITH TIME ZONE,
confirmed_at TIMESTAMP(6) WITH TIME ZONE,
started_at TIMESTAMP(6) WITH TIME ZONE,
finished_at TIMESTAMP(6) WITH TIME ZONE,
retention_until TIMESTAMP(6) WITH TIME ZONE NOT NULL,
created_at TIMESTAMP(6) WITH TIME ZONE NOT NULL,
updated_at TIMESTAMP(6) WITH TIME ZONE NOT NULL,
PRIMARY KEY (id),
CONSTRAINT uq_import_batch_company_id UNIQUE (property_company_id, id),
CONSTRAINT fk_import_batch_company FOREIGN KEY(property_company_id) REFERENCES
property_companies (id),
CONSTRAINT fk_import_batch_community FOREIGN KEY(property_company_id, community_id) REFERENCES
communities (property_company_id, id),
CONSTRAINT fk_import_batch_parent FOREIGN KEY(property_company_id, parent_batch_id) REFERENCES
import_batches (property_company_id, id),
CONSTRAINT fk_import_batch_creator FOREIGN KEY(created_by_scope, created_by_id) REFERENCES
admin_accounts (scope, id),
CONSTRAINT ck_import_batch_scope CHECK ((scope_type = 'company' AND community_id IS NULL) OR
(scope_type = 'community' AND community_id IS NOT NULL)),
CONSTRAINT ck_import_batch_mode CHECK (mode = 'create' AND template_version_no > 0),
CONSTRAINT ck_import_batch_json CHECK (jsonb_typeof(scope_snapshot) = 'object'),
CONSTRAINT ck_import_batch_digests CHECK (template_config_hash ~ '^[0-9a-f]{64}$' AND
(preview_fingerprint IS NULL OR preview_fingerprint ~ '^[0-9a-f]{64}$')),
CONSTRAINT ck_import_batch_status CHECK (status IN ('draft','uploading','prechecking',
'preview_ready','executing','completed','partial_failed','failed','blocked','cancel_requested',
'cancelled','expired')),
CONSTRAINT ck_import_batch_confirmation CHECK ((confirmed_at IS NULL AND apply_policy IS NULL
AND include_warning_rows IS NULL) OR (confirmed_at IS NOT NULL AND apply_policy IS NOT NULL AND
apply_policy IN ('all_rows','valid_rows_only') AND include_warning_rows IS NOT NULL)),
CONSTRAINT ck_import_batch_preview CHECK ((preview_version = 0 AND preview_fingerprint IS NULL
AND preview_expires_at IS NULL) OR (preview_version > 0 AND preview_fingerprint IS NOT NULL AND
preview_expires_at IS NOT NULL)),
CONSTRAINT ck_import_batch_statistics CHECK (total_rows >= 0 AND planned_create_rows >= 0 AND
planned_update_rows >= 0 AND planned_skip_rows >= 0 AND warning_rows >= 0 AND error_rows >= 0
AND created_rows >= 0 AND updated_rows >= 0 AND skipped_rows >= 0 AND failed_rows >= 0 AND
uncertain_rows >= 0 AND cancelled_rows >= 0 AND processed_rows >= 0 AND preview_version >= 0
AND row_version > 0 AND processed_rows <= total_rows AND planned_update_rows = 0 AND
updated_rows = 0),
CONSTRAINT ck_import_batch_finished CHECK (((status IN ('completed','partial_failed','failed',
'cancelled','expired')) = (finished_at IS NOT NULL)) AND (uncertain_rows = 0 OR status NOT IN
('completed','partial_failed','failed','cancelled','expired')))
)
""")
    op.execute("""
CREATE INDEX ix_import_batch_company_time ON import_batches (property_company_id, created_at,
id)
""")
    op.execute("""
CREATE INDEX ix_import_batch_creator ON import_batches (created_by_scope, created_by_id)
""")
    op.execute("""
CREATE INDEX ix_import_batch_parent ON import_batches (property_company_id, parent_batch_id)
""")
    op.execute("""
CREATE INDEX ix_import_batch_retention ON import_batches (retention_until, id)
""")
    op.execute("""
CREATE INDEX ix_import_batch_scope_status ON import_batches (property_company_id, community_id,
status, created_at, id)
""")
    op.execute("""
CREATE INDEX ix_import_batch_template ON import_batches (template_key, template_version_no,
template_config_hash)
""")
    op.execute("""
CREATE TABLE import_requests (
id UUID NOT NULL,
property_company_id UUID NOT NULL,
actor_scope VARCHAR(32) NOT NULL,
actor_id UUID NOT NULL,
request_scope VARCHAR(64) NOT NULL,
idempotency_key VARCHAR(128) NOT NULL,
request_fingerprint CHAR(64) NOT NULL,
batch_id UUID NOT NULL,
http_status SMALLINT NOT NULL,
response_body JSONB NOT NULL,
created_at TIMESTAMP(6) WITH TIME ZONE NOT NULL,
PRIMARY KEY (id),
CONSTRAINT uq_import_request_identity UNIQUE (property_company_id, actor_scope, actor_id,
request_scope, idempotency_key),
CONSTRAINT fk_import_request_company FOREIGN KEY(property_company_id) REFERENCES
property_companies (id),
CONSTRAINT fk_import_request_actor FOREIGN KEY(actor_scope, actor_id) REFERENCES
admin_accounts (scope, id),
CONSTRAINT fk_import_request_batch FOREIGN KEY(property_company_id, batch_id) REFERENCES
import_batches (property_company_id, id),
CONSTRAINT ck_import_request_scope CHECK (request_scope = 'create' OR request_scope IN
('source_file:' || batch_id::text,'precheck:' || batch_id::text,'confirm:' || batch_id::text,
'cancel:' || batch_id::text,'retry_failed:' || batch_id::text,'error_file:' || batch_id::text,
'recover:' || batch_id::text)),
CONSTRAINT ck_import_request_response CHECK (jsonb_typeof(response_body) = 'object' AND
((http_status = 201 AND request_scope IN ('create','retry_failed:' || batch_id::text)) OR
(http_status = 202 AND request_scope NOT IN ('create','retry_failed:' || batch_id::text)))),
CONSTRAINT ck_import_request_digest CHECK (request_fingerprint ~ '^[0-9a-f]{64}$' AND
idempotency_key ~ '^[A-Za-z0-9_-]{1,128}$')
)
""")
    op.execute("""
CREATE INDEX ix_import_request_actor ON import_requests (actor_scope, actor_id)
""")
    op.execute("""
CREATE INDEX ix_import_request_batch ON import_requests (property_company_id, batch_id,
created_at)
""")
    op.execute("""
CREATE TABLE import_artifacts (
id UUID NOT NULL,
batch_id UUID NOT NULL,
artifact_kind VARCHAR(16) NOT NULL,
generation INTEGER DEFAULT '1' NOT NULL,
source_preview_version BIGINT,
storage_key VARCHAR(512) NOT NULL,
original_filename VARCHAR(255),
media_type VARCHAR(128) NOT NULL,
sha256 CHAR(64) NOT NULL,
byte_size BIGINT NOT NULL,
row_count BIGINT,
expires_at TIMESTAMP(6) WITH TIME ZONE NOT NULL,
deleted_at TIMESTAMP(6) WITH TIME ZONE,
created_at TIMESTAMP(6) WITH TIME ZONE NOT NULL,
updated_at TIMESTAMP(6) WITH TIME ZONE NOT NULL,
PRIMARY KEY (id),
CONSTRAINT fk_import_artifact_batch FOREIGN KEY(batch_id) REFERENCES import_batches (id),
CONSTRAINT uq_import_artifact_generation UNIQUE (batch_id, artifact_kind, generation),
CONSTRAINT ck_import_artifact_kind CHECK ((artifact_kind = 'source' AND source_preview_version
IS NULL) OR (artifact_kind = 'error_rows' AND source_preview_version IS NOT NULL AND
source_preview_version > 0)),
CONSTRAINT ck_import_artifact_size CHECK (generation > 0 AND byte_size >= 0 AND (row_count IS
NULL OR row_count >= 0)),
CONSTRAINT ck_import_artifact_digest CHECK (sha256 ~ '^[0-9a-f]{64}$')
)
""")
    op.execute("""
CREATE INDEX ix_import_artifact_expiry ON import_artifacts (expires_at, id)
""")
    op.execute("""
CREATE UNIQUE INDEX ix_import_artifact_source ON import_artifacts (batch_id) WHERE
artifact_kind = 'source'
""")
    op.execute("""
CREATE TABLE import_operations (
id UUID NOT NULL,
property_company_id UUID NOT NULL,
operation_key CHAR(64) NOT NULL,
operation_type VARCHAR(64) NOT NULL,
natural_key JSONB,
input_fingerprint CHAR(64) NOT NULL,
status VARCHAR(16) DEFAULT 'ready' NOT NULL,
target_type VARCHAR(64),
target_id UUID,
attempt_count BIGINT DEFAULT '0' NOT NULL,
last_attempt_at TIMESTAMP(6) WITH TIME ZONE,
processed_at TIMESTAMP(6) WITH TIME ZONE,
sensitive_cleared_at TIMESTAMP(6) WITH TIME ZONE,
created_at TIMESTAMP(6) WITH TIME ZONE NOT NULL,
updated_at TIMESTAMP(6) WITH TIME ZONE NOT NULL,
PRIMARY KEY (id),
CONSTRAINT fk_import_operation_company FOREIGN KEY(property_company_id) REFERENCES
property_companies (id),
CONSTRAINT uq_import_operation_key UNIQUE (property_company_id, operation_key),
CONSTRAINT ck_import_operation_identity CHECK (operation_key ~ '^[0-9a-f]{64}$' AND
input_fingerprint ~ '^[0-9a-f]{64}$'),
CONSTRAINT ck_import_operation_natural_key CHECK ((natural_key IS NULL) =
(sensitive_cleared_at IS NOT NULL) AND (natural_key IS NULL OR jsonb_typeof(natural_key) =
'object')),
CONSTRAINT ck_import_operation_status CHECK (status IN ('ready','running','succeeded',
'skipped','failed','uncertain') AND (status NOT IN ('succeeded','skipped','failed','uncertain')
OR processed_at IS NOT NULL)),
CONSTRAINT ck_import_operation_target CHECK ((target_type IS NULL) = (target_id IS NULL)),
CONSTRAINT ck_import_operation_attempts CHECK (attempt_count >= 0)
)
""")
    op.execute("""
CREATE INDEX ix_import_operation_company_status ON import_operations (property_company_id,
status, id)
""")
    op.execute("""
CREATE TABLE import_rows (
id UUID NOT NULL,
batch_id UUID NOT NULL,
source_row_no BIGINT NOT NULL,
raw_values JSONB,
normalized_values JSONB,
validation_status VARCHAR(16) DEFAULT 'staged' NOT NULL,
planned_action VARCHAR(16) DEFAULT 'none' NOT NULL,
operation_id UUID,
warning_count INTEGER DEFAULT '0' NOT NULL,
error_count INTEGER DEFAULT '0' NOT NULL,
validation_version BIGINT DEFAULT '0' NOT NULL,
execution_status VARCHAR(16) DEFAULT 'pending' NOT NULL,
result_at TIMESTAMP(6) WITH TIME ZONE,
sensitive_cleared_at TIMESTAMP(6) WITH TIME ZONE,
created_at TIMESTAMP(6) WITH TIME ZONE NOT NULL,
updated_at TIMESTAMP(6) WITH TIME ZONE NOT NULL,
PRIMARY KEY (id),
CONSTRAINT fk_import_row_batch FOREIGN KEY(batch_id) REFERENCES import_batches (id),
CONSTRAINT fk_import_row_operation FOREIGN KEY(operation_id) REFERENCES import_operations (id),
CONSTRAINT uq_import_row_number UNIQUE (batch_id, source_row_no),
CONSTRAINT uq_import_row_batch_id UNIQUE (batch_id, id),
CONSTRAINT ck_import_row_source CHECK (source_row_no > 0 AND warning_count >= 0 AND
error_count >= 0 AND validation_version >= 0),
CONSTRAINT ck_import_row_values CHECK ((raw_values IS NULL) = (sensitive_cleared_at IS NOT
NULL) AND (sensitive_cleared_at IS NULL OR normalized_values IS NULL) AND (raw_values IS NULL
OR jsonb_typeof(raw_values) = 'object') AND (normalized_values IS NULL OR
jsonb_typeof(normalized_values) = 'object')),
CONSTRAINT ck_import_row_validation CHECK (validation_status IN ('staged','valid','invalid')
AND planned_action IN ('create','update','skip','conflict','none')),
CONSTRAINT ck_import_row_execution CHECK (execution_status IN ('pending','created','skipped',
'failed','uncertain','cancelled','excluded') AND ((execution_status = 'pending') = (result_at
IS NULL)) AND (execution_status NOT IN ('created','skipped','failed','uncertain') OR
operation_id IS NOT NULL))
)
""")
    op.execute("""
CREATE INDEX ix_import_row_execution ON import_rows (batch_id, execution_status, source_row_no)
""")
    op.execute("""
CREATE INDEX ix_import_row_operation ON import_rows (operation_id)
""")
    op.execute("""
CREATE INDEX ix_import_row_validation ON import_rows (batch_id, validation_status,
source_row_no)
""")
    op.execute("""
CREATE TABLE import_issues (
id UUID NOT NULL,
batch_id UUID NOT NULL,
row_id UUID,
preview_version BIGINT NOT NULL,
phase VARCHAR(16) NOT NULL,
severity VARCHAR(16) NOT NULL,
code VARCHAR(128) NOT NULL,
field_key VARCHAR(64),
column_name VARCHAR(128),
column_index INTEGER,
cell_reference VARCHAR(32),
message VARCHAR(1000) NOT NULL,
suggestion VARCHAR(1000),
detail JSONB,
created_at TIMESTAMP(6) WITH TIME ZONE NOT NULL,
PRIMARY KEY (id),
CONSTRAINT fk_import_issue_batch FOREIGN KEY(batch_id) REFERENCES import_batches (id),
CONSTRAINT fk_import_issue_row FOREIGN KEY(batch_id, row_id) REFERENCES import_rows (batch_id,
id),
CONSTRAINT uq_import_issue_identity UNIQUE NULLS NOT DISTINCT (batch_id, row_id,
preview_version, phase, code, field_key, column_name, column_index, cell_reference),
CONSTRAINT ck_import_issue_phase CHECK ((phase = 'parse' AND preview_version = 0) OR (phase IN
('precheck','apply') AND preview_version > 0)),
CONSTRAINT ck_import_issue_severity CHECK (severity IN ('warning','error')),
CONSTRAINT ck_import_issue_location CHECK (column_index IS NULL OR column_index > 0),
CONSTRAINT ck_import_issue_detail CHECK (detail IS NULL OR jsonb_typeof(detail) = 'object')
)
""")
    op.execute("""
CREATE INDEX ix_import_issue_code ON import_issues (batch_id, code, id)
""")
    op.execute("""
CREATE INDEX ix_import_issue_preview ON import_issues (batch_id, preview_version, severity,
row_id)
""")
    op.execute("""
CREATE TABLE import_tasks (
id UUID NOT NULL,
batch_id UUID NOT NULL,
phase VARCHAR(16) NOT NULL,
status VARCHAR(16) DEFAULT 'ready' NOT NULL,
next_run_at TIMESTAMP(6) WITH TIME ZONE NOT NULL,
attempt_count BIGINT DEFAULT '0' NOT NULL,
lease_expires_at TIMESTAMP(6) WITH TIME ZONE,
progress_done BIGINT DEFAULT '0' NOT NULL,
progress_total BIGINT DEFAULT '0' NOT NULL,
checkpoint JSONB NOT NULL,
last_error_code VARCHAR(128),
started_at TIMESTAMP(6) WITH TIME ZONE,
completed_at TIMESTAMP(6) WITH TIME ZONE,
created_at TIMESTAMP(6) WITH TIME ZONE NOT NULL,
updated_at TIMESTAMP(6) WITH TIME ZONE NOT NULL,
PRIMARY KEY (id),
CONSTRAINT fk_import_task_batch FOREIGN KEY(batch_id) REFERENCES import_batches (id),
CONSTRAINT uq_import_task_phase UNIQUE (batch_id, phase),
CONSTRAINT ck_import_task_phase CHECK (phase IN ('parse','precheck','apply','artifact')),
CONSTRAINT ck_import_task_status CHECK (status IN ('ready','running','completed','paused',
'cancelled')),
CONSTRAINT ck_import_task_lease CHECK ((status = 'running') = (lease_expires_at IS NOT NULL)),
CONSTRAINT ck_import_task_progress CHECK (attempt_count >= 0 AND progress_done >= 0 AND
progress_total >= 0 AND progress_done <= progress_total),
CONSTRAINT ck_import_task_checkpoint CHECK (jsonb_typeof(checkpoint) = 'object' AND checkpoint
? 'schema_version' AND jsonb_typeof(checkpoint->'schema_version') = 'number' AND
checkpoint->>'schema_version' = '1')
)
""")
    op.execute("""
CREATE INDEX ix_import_task_ready ON import_tasks (status, next_run_at, id) WHERE status =
'ready'
""")
    op.execute("""
CREATE INDEX ix_import_task_running ON import_tasks (status, lease_expires_at, id) WHERE status
= 'running'
""")
    op.execute("""
CREATE TABLE import_batch_events (
id UUID NOT NULL,
batch_id UUID NOT NULL,
sequence_no BIGINT NOT NULL,
event_key VARCHAR(128) NOT NULL,
event_type VARCHAR(32) NOT NULL,
from_status VARCHAR(24),
to_status VARCHAR(24),
actor_scope VARCHAR(32),
actor_id UUID,
task_id UUID,
task_attempt BIGINT,
safe_metadata JSONB NOT NULL,
created_at TIMESTAMP(6) WITH TIME ZONE NOT NULL,
PRIMARY KEY (id),
CONSTRAINT fk_import_event_batch FOREIGN KEY(batch_id) REFERENCES import_batches (id),
CONSTRAINT fk_import_event_actor FOREIGN KEY(actor_scope, actor_id) REFERENCES admin_accounts
(scope, id),
CONSTRAINT fk_import_event_task FOREIGN KEY(task_id) REFERENCES import_tasks (id),
CONSTRAINT uq_import_event_sequence UNIQUE (batch_id, sequence_no),
CONSTRAINT uq_import_event_key UNIQUE (batch_id, event_key),
CONSTRAINT ck_import_event_sequence CHECK (sequence_no > 0 AND (task_attempt IS NULL OR
task_attempt > 0)),
CONSTRAINT ck_import_event_actor CHECK ((actor_scope IS NULL) = (actor_id IS NULL)),
CONSTRAINT ck_import_event_metadata CHECK (jsonb_typeof(safe_metadata) = 'object'),
CONSTRAINT ck_import_event_status CHECK ((from_status IS NULL OR from_status IN ('draft',
'uploading','prechecking','preview_ready','executing','completed','partial_failed','failed',
'blocked','cancel_requested','cancelled','expired')) AND (to_status IS NULL OR to_status IN
('draft','uploading','prechecking','preview_ready','executing','completed','partial_failed',
'failed','blocked','cancel_requested','cancelled','expired')))
)
""")
    op.execute("""
CREATE INDEX ix_import_event_actor ON import_batch_events (actor_scope, actor_id)
""")
    op.execute("""
CREATE INDEX ix_import_event_task ON import_batch_events (task_id, created_at)
""")
    _install_immutability_guards()


def _install_immutability_guards() -> None:
    op.execute("""
CREATE FUNCTION import_guard_history() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_TABLE_NAME IN ('import_requests', 'import_batch_events') THEN
        RAISE EXCEPTION 'import evidence is append-only' USING ERRCODE = '23514',
            CONSTRAINT = 'ck_import_history_immutable';
    ELSIF TG_TABLE_NAME = 'import_batches' THEN
        IF (NEW.id,NEW.property_company_id,NEW.community_id,NEW.scope_type,NEW.scope_snapshot,
            NEW.template_key,NEW.template_version_no,NEW.template_config_hash,NEW.mode,
            NEW.parent_batch_id,NEW.created_by_scope,NEW.created_by_id,NEW.request_id,
            NEW.retention_until,NEW.created_at) IS DISTINCT FROM
           (OLD.id,OLD.property_company_id,OLD.community_id,OLD.scope_type,OLD.scope_snapshot,
            OLD.template_key,OLD.template_version_no,OLD.template_config_hash,OLD.mode,
            OLD.parent_batch_id,OLD.created_by_scope,OLD.created_by_id,OLD.request_id,
            OLD.retention_until,OLD.created_at) OR
           (OLD.confirmed_at IS NOT NULL AND
             (NEW.apply_policy IS DISTINCT FROM OLD.apply_policy OR
              NEW.include_warning_rows IS DISTINCT FROM OLD.include_warning_rows OR
              NEW.confirmed_at IS DISTINCT FROM OLD.confirmed_at)) THEN
            RAISE EXCEPTION 'import batch identity or confirmed policy is immutable'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_import_history_immutable';
        END IF;
    ELSIF TG_TABLE_NAME = 'import_rows' THEN
        IF (NEW.batch_id, NEW.source_row_no, NEW.id, NEW.created_at) IS DISTINCT FROM
           (OLD.batch_id, OLD.source_row_no, OLD.id, OLD.created_at) OR
           (NEW.raw_values IS DISTINCT FROM OLD.raw_values AND NOT
             (NEW.raw_values IS NULL AND NEW.sensitive_cleared_at IS NOT NULL)) OR
           (OLD.normalized_values IS NOT NULL AND
             NEW.normalized_values IS DISTINCT FROM OLD.normalized_values AND NOT
             (NEW.normalized_values IS NULL AND NEW.sensitive_cleared_at IS NOT NULL)) OR
           (EXISTS (SELECT 1 FROM import_batches WHERE id = OLD.batch_id AND status IN
             ('completed','partial_failed','failed','cancelled','expired')) AND
             (NEW.execution_status,NEW.result_at,NEW.operation_id) IS DISTINCT FROM
             (OLD.execution_status,OLD.result_at,OLD.operation_id)) THEN
            RAISE EXCEPTION 'import row input or finished result is immutable'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_import_history_immutable';
        END IF;
    ELSIF TG_TABLE_NAME = 'import_operations' THEN
        IF (NEW.property_company_id,NEW.operation_key,NEW.operation_type,
            NEW.input_fingerprint,NEW.id,NEW.created_at) IS DISTINCT FROM
           (OLD.property_company_id,OLD.operation_key,OLD.operation_type,
            OLD.input_fingerprint,OLD.id,OLD.created_at) OR
           (OLD.natural_key IS DISTINCT FROM NEW.natural_key AND NOT
             (NEW.natural_key IS NULL AND NEW.sensitive_cleared_at IS NOT NULL)) OR
           (OLD.status IN ('succeeded','skipped') AND
             (NEW.status,NEW.target_type,NEW.target_id) IS DISTINCT FROM
             (OLD.status,OLD.target_type,OLD.target_id)) THEN
            RAISE EXCEPTION 'import operation identity or success is immutable'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_import_history_immutable';
        END IF;
    END IF;
    RETURN NEW;
END $$
""")
    for table in ("import_requests", "import_batch_events"):
        op.execute(
            f"CREATE TRIGGER import_guard_history BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION import_guard_history()"
        )
    for table in ("import_batches", "import_rows", "import_operations"):
        op.execute(
            f"CREATE TRIGGER import_guard_history BEFORE UPDATE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION import_guard_history()"
        )


def downgrade() -> None:
    connection = op.get_bind()
    for table in TABLES:
        if connection.scalar(sa.text(f"SELECT EXISTS (SELECT 1 FROM {table})")):
            raise RuntimeError("Cannot downgrade while import history exists")
    for table in reversed(TABLES):
        op.drop_table(table)

    op.execute("DROP FUNCTION import_guard_history()")
