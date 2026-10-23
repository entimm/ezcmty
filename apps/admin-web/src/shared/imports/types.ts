import type { Page } from '../api/admin';
export type ScopeType = 'company' | 'community';
export type BatchStatus =
  | 'draft'
  | 'uploading'
  | 'prechecking'
  | 'preview_ready'
  | 'executing'
  | 'completed'
  | 'partial_failed'
  | 'failed'
  | 'blocked'
  | 'cancel_requested'
  | 'cancelled'
  | 'expired';
export type NextAction =
  | 'upload_source_file'
  | 'precheck'
  | 'confirm'
  | 'cancel'
  | 'retry_failed'
  | 'recover'
  | 'generate_error_file'
  | 'download_error_file';
export type Scalar = string | number | boolean | null;
export interface Version {
  version_no: number;
  config_hash: string;
  available_for_new_batches: boolean;
  template_downloadable: boolean;
  released_at: string;
  release_notes: string;
}
export interface ImportType {
  key: string;
  name: string;
  allowed_scope_types: ScopeType[];
  supported_modes: ['create'];
  versions: Version[];
}
export interface TemplateField {
  key: string;
  label: string;
  order: number;
  required: boolean;
  data_type: string;
  max_length: number | null;
  format: string | null;
  enum_values: Scalar[];
  example: Scalar;
  description: string;
  normalization_rules: string[];
}
export interface Template {
  key: string;
  name: string;
  version_no: number;
  config_hash: string;
  available_for_new_batches: boolean;
  released_at: string;
  release_notes: string;
  fields: TemplateField[];
}
export interface TaskIdentity {
  id: string;
  phase: 'parse' | 'precheck' | 'apply' | 'artifact';
  status: 'ready' | 'running' | 'completed' | 'paused' | 'cancelled';
}
export interface Task extends TaskIdentity {
  progress_done: number;
  progress_total: number | null;
  updated_at: string;
  last_error_code: string | null;
}
export interface BatchAction {
  batch_id: string;
  status: BatchStatus;
  phase: string;
  preview_version: number;
  active_task: TaskIdentity | null;
  source_artifact: { id: string; size_bytes: number; sha256: string } | null;
}
export interface BatchCreate {
  import_type: string;
  template_version_no: number;
  scope: { type: ScopeType; id: string };
  mode: 'create';
  property_company_id?: string;
}
export interface ConfirmInput {
  preview_version: number;
  preview_fingerprint: string;
  apply_policy: 'all_rows' | 'valid_rows_only';
  include_warning_rows: boolean;
}
export interface BusinessField {
  key: string;
  label: string;
  format: 'text' | 'money_cents';
}
export interface BusinessPreview {
  fields: BusinessField[];
  summary: {
    key: string;
    label: string;
    format: 'integer' | 'money_cents';
    without_warning_rows: string;
    with_warning_rows: string;
  }[];
}
export interface Batch {
  id: string;
  parent_batch_id: string | null;
  import_type: string;
  import_type_name: string;
  property_company_id: string;
  template: { key: string; version_no: number; config_hash: string };
  scope: { type: ScopeType; id: string; name: string };
  mode: 'create';
  status: BatchStatus;
  phase: string;
  last_error_code: string | null;
  blocked_reason: string | null;
  preview: {
    version: number;
    fingerprint: string;
    generated_at: string;
    expires_at: string;
  } | null;
  apply_policy: ConfirmInput['apply_policy'] | null;
  include_warning_rows: boolean | null;
  business_preview?: BusinessPreview | null;
  statistics: {
    total_rows: number;
    preview: {
      create_rows: number;
      update_rows: number;
      skip_rows: number;
      warning_rows: number;
      error_rows: number;
    };
    execution: {
      created_rows: number;
      updated_rows: number;
      skipped_rows: number;
      failed_rows: number;
      uncertain_rows: number;
      cancelled_rows: number;
      excluded_rows: number;
      processed_rows: number;
      retryable_failed_rows: number;
    };
  };
  source_artifact: {
    id: string;
    file_name: string | null;
    media_type: string;
    size_bytes: number;
    sha256: string;
    expires_at: string;
    available: boolean;
  } | null;
  active_task: Task | null;
  created_by: { id: string; name: string };
  created_at: string;
  updated_at: string;
  retention_until: string;
  confirmed_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  next_actions: NextAction[];
}
export interface ImportRow {
  id: string;
  row_no: number;
  precheck_status: 'pending' | 'valid' | 'warning' | 'error';
  planned_action: 'none' | 'create' | 'skip' | 'conflict';
  raw_values: Record<string, Scalar>;
  normalized_values: Record<string, Scalar> | null;
  business_values?: Record<string, Scalar> | null;
  issue_count: number;
  execution_status:
    | 'pending'
    | 'created'
    | 'skipped'
    | 'failed'
    | 'uncertain'
    | 'cancelled'
    | 'excluded';
  result_code: string | null;
  result_message: string | null;
  result_at: string | null;
}
export interface Issue {
  id: string;
  preview_version: number;
  phase: 'parse' | 'precheck' | 'apply';
  row_no: number | null;
  column_index: number | null;
  column_name: string | null;
  field_key: string | null;
  cell_reference: string | null;
  severity: 'warning' | 'error';
  code: string;
  message: string;
  suggestion: string | null;
  raw_value: Scalar;
  normalized_value: Scalar;
  retryable: boolean;
}
export interface ImportEvent {
  id: string;
  event_type: string;
  phase: TaskIdentity['phase'] | null;
  message: string;
  created_at: string;
}
export interface ErrorFile {
  batch_id: string;
  status:
    | 'not_generated'
    | 'queued'
    | 'generating'
    | 'ready'
    | 'stale'
    | 'failed'
    | 'expired';
  generation: number | null;
  source_preview_version: number | null;
  format: 'csv' | 'xlsx' | null;
  task: Task | null;
  file_name: string | null;
  media_type: string | null;
  size_bytes: number | null;
  sha256: string | null;
  generated_at: string | null;
  expires_at: string | null;
  last_error_code: string | null;
  downloadable: boolean;
}
export type Filters = Record<string, string | number | boolean | undefined>;
export type { Page };
