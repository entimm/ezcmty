import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { App } from 'antd';
import { describe, expect, it, vi } from 'vitest';
import { PropertyImportsPage } from '../../../src/features/property/imports';
import {
  AdminContext,
  type AdminContextValue,
} from '../../../src/shared/context';
import type {
  Batch,
  ImportRow,
  Template,
} from '../../../src/shared/imports/types';
import type { AdminRequest, RequestOptions } from '../../../src/shared/request';

const importType = 'property_fee_basis_versions';
const batchId = '00000000-0000-4000-8000-000000000001';
const companyId = '00000000-0000-4000-8000-000000000002';
const community = {
  id: '00000000-0000-4000-8000-000000000003',
  name: '锦绣华庭',
  property_company_id: companyId,
  enabled: true,
};
const template: Template = {
  key: importType,
  name: '房屋计费依据',
  version_no: 1,
  config_hash: 'a'.repeat(64),
  available_for_new_batches: true,
  released_at: '2026-10-28T00:00:00Z',
  release_notes: '为已有房屋追加不可变依据版本。',
  fields: [
    {
      key: 'effective_from_month',
      label: '生效月份',
      order: 1,
      required: true,
      data_type: 'string',
      max_length: 7,
      format: null,
      enum_values: [],
      example: '2026-10',
      description: '使用YYYY-MM文本，支持历史、当前、未来月份。',
      normalization_rules: ['trim'],
    },
  ],
};

function previewBatch(): Batch {
  const now = new Date().toISOString();
  const expires = new Date(Date.now() + 60 * 60 * 1000).toISOString();
  return {
    id: batchId,
    parent_batch_id: null,
    import_type: importType,
    import_type_name: template.name,
    property_company_id: companyId,
    template: {
      key: importType,
      version_no: 1,
      config_hash: template.config_hash,
    },
    template_fields: template.fields,
    scope: { type: 'community', id: community.id, name: community.name },
    mode: 'create',
    status: 'preview_ready',
    phase: 'awaiting_confirmation',
    last_error_code: null,
    blocked_reason: null,
    preview: {
      version: 1,
      fingerprint: 'b'.repeat(64),
      generated_at: now,
      expires_at: expires,
    },
    apply_policy: null,
    include_warning_rows: null,
    statistics: {
      total_rows: 1,
      preview: {
        create_rows: 1,
        update_rows: 0,
        skip_rows: 0,
        warning_rows: 0,
        error_rows: 0,
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
    business_preview: {
      fields: [
        { key: 'house_label', label: '完整房屋位置', format: 'text' },
        { key: 'effective_from_month', label: '生效月份', format: 'text' },
        { key: 'comparison_version', label: '同月比较版本', format: 'text' },
        { key: 'old_basis', label: '旧标准', format: 'text' },
        { key: 'new_basis', label: '输入标准', format: 'text' },
        { key: 'changes', label: '具体字段变化', format: 'text' },
        {
          key: 'calculated_amount_cents',
          label: '输入月费试算',
          format: 'money_cents',
        },
        { key: 'effective_period', label: '适用区间', format: 'text' },
      ],
      summary: [],
    },
    source_artifact: {
      id: batchId,
      file_name: '计费依据.csv',
      media_type: 'text/csv',
      size_bytes: 200,
      sha256: 'c'.repeat(64),
      expires_at: expires,
      available: true,
    },
    active_task: null,
    created_by: { id: companyId, name: '计费依据维护员' },
    created_at: now,
    updated_at: now,
    retention_until: expires,
    confirmed_at: null,
    started_at: null,
    finished_at: null,
    next_actions: ['confirm', 'generate_error_file'],
  };
}

const row: ImportRow = {
  id: batchId,
  row_no: 2,
  precheck_status: 'valid',
  planned_action: 'create',
  raw_values: {},
  normalized_values: {},
  business_values: {
    house_label: '锦绣华庭／1栋／0101',
    effective_from_month: '2026-10',
    comparison_version: 'v2',
    old_basis: '住宅；100㎡ × 1.00元/㎡',
    new_basis: '住宅；100㎡ × 1.20元/㎡',
    changes: '月单价：1.00元 → 1.20元',
    calculated_amount_cents: 12000,
    effective_period: '2026-10 至 2026-12 前',
  },
  issue_count: 0,
  execution_status: 'pending',
  result_code: null,
  result_message: null,
  result_at: null,
};

function show(page: 'import-new' | 'import-detail', permissions: string[]) {
  const batch = previewBatch();
  const calls: { path: string; options?: RequestOptions }[] = [];
  const request = (async (path: string, options?: RequestOptions) => {
    calls.push({ path, options });
    if (options?.method === 'POST')
      return {
        batch_id: batchId,
        status: 'prechecking',
        phase: 'parse_queued',
        preview_version: 0,
        active_task: null,
        source_artifact: null,
      };
    if (path === '/v1/property-workspace/context')
      return {
        property_company_id: companyId,
        property_company_name: '锦城物业',
      };
    if (path === '/v1/import-types')
      return {
        items: [
          {
            key: importType,
            name: template.name,
            allowed_scope_types: ['community'],
            supported_modes: ['create'],
            versions: [{ ...template, template_downloadable: true }],
          },
        ],
      };
    if (path === `/v1/import-types/${importType}/versions/1`) return template;
    if (path === `/v1/import-batches/${batchId}`) return batch;
    if (path.includes('/rows?'))
      return { items: [row], total: 1, page: 1, page_size: 20 };
    if (path.includes('/issues?') || path.includes('/events?'))
      return { items: [], total: 0, page: 1, page_size: 20 };
    if (path.endsWith('/artifacts/error-file'))
      return { status: 'not_generated', downloadable: false };
    throw new Error(`Unexpected request: ${path}`);
  }) as AdminRequest;
  const go = vi.fn();
  const can = (permission: string) => permissions.includes(permission);
  const context: AdminContextValue = {
    scope: 'property',
    request,
    can,
    hasPermission: can,
    session: {
      scope: 'property_admin',
      subjectId: 'basis-manager',
      loginName: 'basis-manager',
      displayName: '依据维护员',
      permissions,
      mustChangePassword: false,
      csrfToken: 'csrf',
    },
    refreshSession: vi.fn(),
    communityId: community.id,
    community,
    communities: [community],
    go,
    page,
    params: { id: batchId, import_type: importType },
    setDirty: vi.fn(),
    confirmLeave: (next) => next(),
  };
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  const view = render(
    <QueryClientProvider client={client}>
      <AdminContext.Provider value={context}>
        <App>
          <PropertyImportsPage page={page} params={context.params} go={go} />
        </App>
      </AdminContext.Provider>
    </QueryClientProvider>,
  );
  return { ...view, calls, go, batch };
}

describe('房屋计费依据导入', () => {
  it('仅依据维护角色通过通用入口读取模板并上传至当前小区', async () => {
    const { container, calls, go } = show('import-new', [
      'property.bill.read',
      'property.fee_basis.manage',
    ]);
    fireEvent.click(
      await screen.findByRole('button', { name: /下一步：准备文件/ }),
    );
    expect(
      await screen.findByText('使用YYYY-MM文本，支持历史、当前、未来月份。'),
    ).toBeInTheDocument();
    expect(screen.getByText(/同批每房最多一行/)).toHaveTextContent(
      '已建账单不变，已有后续生效安排保留',
    );
    fireEvent.change(container.querySelector('input[type="file"]')!, {
      target: { files: [new File(['楼栋,房号\n1栋,0101'], '计费依据.csv')] },
    });
    fireEvent.click(screen.getByRole('button', { name: '创建草稿并预检' }));
    await waitFor(() =>
      expect(go).toHaveBeenCalledWith('import-detail', {
        id: batchId,
        return: undefined,
      }),
    );
    const creation = calls.find(
      (call) =>
        call.path === '/v1/import-batches' && call.options?.method === 'POST',
    );
    expect(JSON.parse(String(creation?.options?.body))).toEqual({
      import_type: importType,
      template_version_no: 1,
      scope: { type: 'community', id: community.id },
      mode: 'create',
    });
    expect(
      calls.find((call) => call.path.endsWith('/source-file'))?.options?.body,
    ).toBeInstanceOf(FormData);
    expect(calls.some((call) => call.path.includes('/houses'))).toBe(false);
  });

  it('预览安全业务差异与单行月费，依据维护可按原预览确认且不显示应收合计', async () => {
    const { calls, batch } = show('import-detail', [
      'property.bill.read',
      'property.fee_basis.manage',
    ]);
    expect(await screen.findByText('锦绣华庭／1栋／0101')).toBeInTheDocument();
    expect(screen.getByText('v2')).toBeInTheDocument();
    expect(screen.getByText('月单价：1.00元 → 1.20元')).toBeInTheDocument();
    expect(screen.getByText('¥120.00')).toBeInTheDocument();
    expect(screen.getByText('2026-10 至 2026-12 前')).toBeInTheDocument();
    expect(screen.queryByText('预计新增应收')).not.toBeInTheDocument();
    expect(screen.queryByText('预计待缴')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '确认执行' }));
    fireEvent.click(screen.getByRole('radio', { name: '排除警告行' }));
    fireEvent.click(
      screen.getByRole('button', { name: '下一步：核对影响范围' }),
    );
    expect(screen.getByText(/同批每房最多一行/)).toHaveTextContent(
      '已建账单不变',
    );
    fireEvent.click(screen.getByRole('checkbox'));
    fireEvent.click(screen.getByRole('button', { name: '确认并安排执行' }));
    await waitFor(() =>
      expect(calls.some((call) => call.path.endsWith('/confirm'))).toBe(true),
    );
    const confirmation = calls.find((call) => call.path.endsWith('/confirm'))!;
    expect(JSON.parse(String(confirmation.options?.body))).toEqual({
      preview_version: batch.preview!.version,
      preview_fingerprint: batch.preview!.fingerprint,
      apply_policy: 'all_rows',
      include_warning_rows: false,
    });
  });

  it('仅账务读取角色可查看依据预览和生成问题清单，不出现执行按钮', async () => {
    show('import-detail', ['property.bill.read']);
    expect(await screen.findByText('锦绣华庭／1栋／0101')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /生成问题清单/ })).toBeEnabled();
    expect(
      screen.queryByRole('button', { name: '确认执行' }),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '查看明细' }));
    expect(await screen.findByText('原始第 2 行')).toBeVisible();
  });
});
