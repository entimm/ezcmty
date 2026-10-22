import { vi } from 'vitest';
import type {
  Batch,
  ErrorFile,
  ImportType,
  Template,
} from '@/shared/imports/types';
import type { AdminScope } from '@/shared/admin-types';
import { mockApi, session } from '../app/platform-harness';
export const batchId = '019a0000-0000-7000-8000-000000000100';
export const hash = 'a'.repeat(64);
export const importType: ImportType = {
  key: 'test_records',
  name: '测试记录导入',
  allowed_scope_types: ['company', 'community'],
  supported_modes: ['create'],
  versions: [
    {
      version_no: 1,
      config_hash: hash,
      available_for_new_batches: true,
      template_downloadable: true,
      released_at: '2026-10-23T00:00:00Z',
      release_notes: '测试模板版本',
    },
  ],
};
export const template: Template = {
  key: importType.key,
  name: importType.name,
  version_no: 1,
  config_hash: hash,
  available_for_new_batches: true,
  released_at: importType.versions[0].released_at,
  release_notes: '测试模板版本',
  fields: [
    {
      key: 'title',
      label: '名称',
      order: 1,
      required: true,
      data_type: 'string',
      max_length: 100,
      format: null,
      enum_values: [],
      example: '示例',
      description: '测试输入',
      normalization_rules: ['去除首尾空格'],
    },
  ],
};
export const batch: Batch = {
  id: batchId,
  parent_batch_id: null,
  import_type: importType.key,
  import_type_name: importType.name,
  property_company_id: '019a0000-0000-7000-8000-000000000001',
  template: { key: importType.key, version_no: 1, config_hash: hash },
  scope: {
    type: 'company',
    id: '019a0000-0000-7000-8000-000000000001',
    name: '测试物业公司',
  },
  mode: 'create',
  status: 'preview_ready',
  phase: 'awaiting_confirmation',
  last_error_code: null,
  blocked_reason: null,
  preview: {
    version: 1,
    fingerprint: hash,
    generated_at: '2026-10-23T00:00:00Z',
    expires_at: '2099-10-24T00:00:00Z',
  },
  apply_policy: null,
  include_warning_rows: null,
  statistics: {
    total_rows: 3,
    preview: {
      create_rows: 2,
      update_rows: 0,
      skip_rows: 1,
      warning_rows: 1,
      error_rows: 1,
    },
    execution: {
      created_rows: 0,
      updated_rows: 0,
      skipped_rows: 0,
      failed_rows: 0,
      uncertain_rows: 0,
      cancelled_rows: 0,
      excluded_rows: 0,
      processed_rows: 0,
      retryable_failed_rows: 0,
    },
  },
  source_artifact: {
    id: batchId,
    file_name: 'input.csv',
    media_type: 'text/csv',
    size_bytes: 123,
    sha256: hash,
    expires_at: '2099-11-23T00:00:00Z',
    available: true,
  },
  active_task: null,
  created_by: { id: 'root', name: '测试管理员' },
  created_at: '2026-10-23T00:00:00Z',
  updated_at: '2026-10-23T00:00:00Z',
  retention_until: '2099-11-23T00:00:00Z',
  confirmed_at: null,
  started_at: null,
  finished_at: null,
  next_actions: ['confirm', 'precheck', 'cancel', 'generate_error_file'],
};
export const errorFile: ErrorFile = {
  batch_id: batchId,
  status: 'not_generated',
  generation: null,
  source_preview_version: null,
  format: null,
  task: null,
  file_name: null,
  media_type: null,
  size_bytes: null,
  sha256: null,
  generated_at: null,
  expires_at: null,
  last_error_code: null,
  downloadable: false,
};
export function mockImports(
  scope: AdminScope,
  permissions: string[],
  override?: (
    path: string,
    init?: RequestInit,
  ) => Response | undefined | Promise<Response | undefined>,
) {
  const identity = {
    ...session,
    scope,
    permissions: [
      ...permissions,
      'property.company.read',
      'property.community.read',
    ],
  };
  const fallback = mockApi(
    scope === 'platform_admin' ? identity : null,
    scope === 'property_admin' ? identity : null,
  );
  const fetcher = vi.fn<typeof fetch>(async (url, init) => {
    const path = new URL(String(url)).pathname;
    const custom = await override?.(path, init);
    if (custom) return custom;
    if (path.endsWith('/import-types'))
      return Response.json({ items: [importType] });
    if (path.endsWith('/versions/1')) return Response.json(template);
    if (path.endsWith('/import-batches'))
      return Response.json({
        items: [batch],
        total: 1,
        page: 1,
        page_size: 20,
      });
    if (path.endsWith(`/import-batches/${batchId}`))
      return Response.json(batch);
    if (path.endsWith('/artifacts/error-file')) return Response.json(errorFile);
    if (['/events', '/rows', '/issues'].some((suffix) => path.endsWith(suffix)))
      return Response.json({ items: [], total: 0, page: 1, page_size: 20 });
    return fallback(url, init);
  });
  vi.stubGlobal('fetch', fetcher);
  return fetcher;
}
