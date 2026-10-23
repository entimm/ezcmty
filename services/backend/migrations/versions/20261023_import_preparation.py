"""Allow a new ordinary precheck generation to replace its preparation snapshot."""

from alembic import op
from sqlalchemy import text

revision = "20261023_import_preparation"
down_revision = "20261022_imports"
branch_labels = None
depends_on = None

_GUARD_SQL = """
CREATE OR REPLACE FUNCTION import_guard_history() RETURNS trigger LANGUAGE plpgsql AS $$
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
             (NEW.normalized_values IS NULL AND NEW.sensitive_cleared_at IS NOT NULL)
             {preparation_exception}) OR
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
"""

_PREPARATION_EXCEPTION = """
             AND NOT (
               NEW.normalized_values IS NOT NULL AND NEW.sensitive_cleared_at IS NULL
               AND OLD.execution_status = 'pending' AND NEW.execution_status = 'pending'
               AND NEW.validation_version > OLD.validation_version
               AND EXISTS (SELECT 1 FROM import_batches b WHERE b.id = OLD.batch_id
                 AND b.parent_batch_id IS NULL AND b.confirmed_at IS NULL
                 AND b.status = 'prechecking'))
"""


def upgrade() -> None:
    op.execute(_GUARD_SQL.format(preparation_exception=_PREPARATION_EXCEPTION))


def downgrade() -> None:
    active = op.get_bind().scalar(
        text("""
        SELECT EXISTS (
          SELECT 1 FROM import_batches b JOIN import_rows r ON r.batch_id = b.id
          WHERE b.parent_batch_id IS NULL AND b.confirmed_at IS NULL
            AND b.status = 'prechecking' AND r.normalized_values IS NOT NULL
            AND r.validation_version > b.preview_version AND r.validation_version > 1)
    """)
    )
    if active:
        raise RuntimeError(
            "An ordinary import recheck is active; finish or cancel it before downgrade"
        )
    op.execute(_GUARD_SQL.format(preparation_exception=""))
