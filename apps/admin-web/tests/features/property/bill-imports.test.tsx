import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { renderRoutes } from '../../app/platform-harness';
import {
  batch,
  batchId,
  importType,
  mockImports,
  template,
} from '../../support/imports';
import type { Batch, ImportType } from '@/shared/imports/types';

const communityId = '019a0000-0000-7000-8000-000000000999';
const houseId = '019a0000-0000-7000-8000-000000000998';
const communityPath = `/api/property/v1/communities/${communityId}`;
const billsRoute = `/property/communities/${communityId}/bills`;
const productionType: ImportType = {
  ...importType,
  key: 'property_fee_bills',
  name: '物业费账单导入',
  allowed_scope_types: ['community'],
};
const fields = [
  { key: 'matched_house_label', label: '匹配房屋', format: 'text' as const },
  { key: 'billing_month', label: '账单月份', format: 'text' as const },
  { key: 'receivable_cents', label: '应收', format: 'money_cents' as const },
  {
    key: 'initial_paid_cents',
    label: '初始已缴',
    format: 'money_cents' as const,
  },
  { key: 'outstanding_cents', label: '待缴', format: 'money_cents' as const },
];
const productionBatch: Batch = {
  ...batch,
  import_type: productionType.key,
  import_type_name: productionType.name,
  template: { ...batch.template, key: productionType.key },
  scope: { type: 'community', id: communityId, name: '第一百零一个小区' },
  business_preview: {
    fields,
    summary: [
      {
        key: 'receivable_cents',
        label: '预计新增应收',
        format: 'money_cents',
        without_warning_rows: '900719925474099300',
        with_warning_rows: '900719925474099700',
      },
      {
        key: 'initial_paid_cents',
        label: '预计初始已缴',
        format: 'money_cents',
        without_warning_rows: '300',
        with_warning_rows: '500',
      },
      {
        key: 'outstanding_cents',
        label: '预计新增待缴',
        format: 'money_cents',
        without_warning_rows: '900719925474099000',
        with_warning_rows: '900719925474099200',
      },
    ],
  },
};
const permissions = [
  'property.import.read',
  'property.import.create',
  'property.import.execute',
  'property.bill.read',
  'property.bill.create',
  'property.house.read',
];
function mockBillImports(
  allowed = permissions,
  currentBatch = productionBatch,
) {
  return mockImports('property_admin', allowed, (path, init) => {
    if (path.endsWith('/import-types'))
      return Response.json({ items: [productionType] });
    if (path.endsWith('/versions/1'))
      return Response.json({
        ...template,
        key: productionType.key,
        name: productionType.name,
      });
    if (path === '/api/property/v1/communities')
      return Response.json({ items: [], total: 125, page: 1, page_size: 100 });
    if (path === communityPath)
      return Response.json({
        id: communityId,
        name: currentBatch.scope.name,
        code: 'LATE',
        property_company_id: batch.property_company_id,
        enabled: true,
      });
    if (path === `${communityPath}/bills`)
      return Response.json({ items: [], total: 0, page: 1, page_size: 20 });
    if (path === `${communityPath}/houses/${houseId}`)
      return Response.json({
        id: houseId,
        community_id: communityId,
        space_node_id: houseId,
        room_no: '001',
        display_address: '第一百零一个小区／A栋／001',
        enabled: true,
        effective_enabled: true,
        ancestors: [],
      });
    if (path.endsWith('/import-batches') && init?.method === 'POST')
      return Response.json(
        {
          batch_id: batchId,
          status: 'draft',
          phase: 'awaiting_source_file',
          preview_version: 0,
          active_task: null,
          source_artifact: null,
        },
        { status: 201 },
      );
    if (path.endsWith(`/import-batches/${batchId}`))
      return Response.json(currentBatch);
    if (path.endsWith('/rows'))
      return Response.json({
        items: [
          {
            id: batchId,
            row_no: 7,
            precheck_status: 'valid',
            planned_action: 'create',
            raw_values: { title: '原始房屋资料' },
            normalized_values: { title: '原始房屋资料' },
            business_values: {
              matched_house_label: '第一百零一个小区／A栋／001',
              billing_month: '2026-10',
              receivable_cents: 12345,
              initial_paid_cents: 300,
              outstanding_cents: 12045,
              private_command: '内部命令不可展示',
            },
            issue_count: 0,
            execution_status: 'pending',
            result_code: null,
            result_message: null,
            result_at: null,
          },
        ],
        total: 125,
        page: 1,
        page_size: 20,
      });
  });
}
afterEach(() => {
  localStorage.clear();
  vi.unstubAllGlobals();
});

it('opens a locked community import from bills and resolves its name beyond the first options page', async () => {
  const fetcher = mockBillImports();
  renderRoutes(billsRoute);
  fireEvent.click(await screen.findByRole('button', { name: '批量导入' }));
  expect(
    await screen.findByText('范围已锁定：第一百零一个小区'),
  ).toBeInTheDocument();
  expect(screen.getByText('来源页面：账单管理')).toBeInTheDocument();
  expect(screen.getByRole('combobox', { name: '导入类型' })).toBeDisabled();
  expect(screen.getByRole('combobox', { name: '范围类型' })).toBeDisabled();
  expect(screen.getByRole('combobox', { name: '导入小区' })).toBeDisabled();
  const create = screen.getByRole('button', {
    name: '创建草稿，下一步上传文件',
  });
  await waitFor(() => expect(create).toBeEnabled());
  fireEvent.click(create);
  await waitFor(() =>
    expect(fetcher.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(
      true,
    ),
  );
  const submission = fetcher.mock.calls.find(
    ([url, init]) =>
      String(url).endsWith('/import-batches') && init?.method === 'POST',
  )!;
  expect(JSON.parse(String(submission[1]?.body))).toEqual({
    import_type: 'property_fee_bills',
    template_version_no: 1,
    scope: { type: 'community', id: communityId },
    mode: 'create',
  });
});

it.each(['property.import.create', 'property.bill.create'])(
  'hides the billing import entry without %s',
  async (missing) => {
    mockBillImports(permissions.filter((permission) => permission !== missing));
    renderRoutes(billsRoute);
    await screen.findByText('物业费账单');
    expect(
      screen.queryByRole('button', { name: '批量导入' }),
    ).not.toBeInTheDocument();
  },
);

it('keeps the house details bill table limited to its individual create entry', async () => {
  mockBillImports();
  renderRoutes(
    `/property/communities/${communityId}/houses/${houseId}?tab=bills`,
  );
  expect(await screen.findByRole('button', { name: '新增账单' })).toBeEnabled();
  expect(
    screen.queryByRole('button', { name: '批量导入' }),
  ).not.toBeInTheDocument();
});

it('uses safe business columns and complete precise totals when confirming warning policy', async () => {
  mockBillImports();
  renderRoutes(`/property/imports/${batchId}`);
  expect(
    await screen.findByText('第一百零一个小区／A栋／001'),
  ).toBeInTheDocument();
  expect(screen.getByText('¥123.45')).toBeInTheDocument();
  expect(screen.queryByText('内部命令不可展示')).not.toBeInTheDocument();
  expect(
    screen.getByText('不含警告行：¥9007199254740993.00'),
  ).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: '确认执行' }));
  const dialog = await screen.findByRole('dialog');
  expect(
    within(dialog).getByText('账单创建后立即生效，请核对房屋、月份和金额。'),
  ).toBeInTheDocument();
  fireEvent.click(
    within(dialog).getByRole('radio', { name: '仅执行通过行，排除普通错误行' }),
  );
  expect(within(dialog).getAllByText('请先选择是否执行警告行')).toHaveLength(3);
  fireEvent.click(within(dialog).getByRole('radio', { name: '排除警告行' }));
  expect(within(dialog).getByText('¥9007199254740993.00')).toBeInTheDocument();
  expect(within(dialog).getByText('¥3.00')).toBeInTheDocument();
  fireEvent.click(within(dialog).getByRole('radio', { name: '执行警告行' }));
  expect(within(dialog).getByText('¥9007199254740997.00')).toBeInTheDocument();
  expect(within(dialog).getByText('¥5.00')).toBeInTheDocument();
});

it('returns to all active bills and loads the company-scoped billing results', async () => {
  const fetcher = mockBillImports(permissions, {
    ...productionBatch,
    status: 'completed',
    phase: 'finished',
    confirmed_at: batch.created_at,
    finished_at: batch.updated_at,
    next_actions: [],
  });
  renderRoutes(`/property/imports/${batchId}`);
  fireEvent.click(await screen.findByRole('button', { name: '返回账单管理' }));
  await waitFor(() =>
    expect(screen.getByTestId('location')).toHaveTextContent(
      `${billsRoute}?view=all`,
    ),
  );
  await waitFor(() =>
    expect(
      fetcher.mock.calls.some(
        ([url]) => new URL(String(url)).pathname === `${communityPath}/bills`,
      ),
    ).toBe(true),
  );
});

it('keeps the billing effect notice without granting a bill reader destination', async () => {
  mockBillImports(
    permissions.filter((permission) => permission !== 'property.bill.read'),
  );
  renderRoutes(`/property/imports/${batchId}`);
  fireEvent.click(await screen.findByRole('button', { name: '确认执行' }));
  const dialog = await screen.findByRole('dialog');
  expect(
    within(dialog).getByText('账单创建后立即生效，请核对房屋、月份和金额。'),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole('button', { name: '返回账单管理' }),
  ).not.toBeInTheDocument();
});
