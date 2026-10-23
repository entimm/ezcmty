import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { QueryClient } from '@tanstack/react-query';
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
const nodeId = '019a0000-0000-7000-8000-000000000998';
const base = `/api/property/v1/communities/${communityId}`;
const route = `/property/communities/${communityId}/houses`;
const ownerType: ImportType = {
  ...importType,
  key: 'house_owners',
  name: '业主登记',
  allowed_scope_types: ['community'],
};
const permissions = [
  'property.house.read',
  'property.house_owner.create',
  'property.house_owner.read',
  'property.import.read',
  'property.import.create',
  'property.import.execute',
  'property.space.read',
];
const ownerBatch: Batch = {
  ...batch,
  import_type: ownerType.key,
  import_type_name: ownerType.name,
  template: { ...batch.template, key: ownerType.key },
  scope: { type: 'community', id: communityId, name: '第一百零一个小区' },
  business_preview: {
    fields: [
      { key: 'house_label', label: '完整位置', format: 'text' },
      { key: 'name', label: '业主姓名', format: 'text' },
      { key: 'phone', label: '规范化手机号', format: 'text' },
      { key: 'owner_status', label: '已有登记状态', format: 'text' },
    ],
    summary: [],
  },
};

function mockOwnerImports({
  allowed = permissions,
  current = ownerBatch,
  communityEnabled = true,
} = {}) {
  return mockImports('property_admin', allowed, (path, init) => {
    if (path.endsWith('/import-types'))
      return Response.json({ items: [ownerType] });
    if (path.endsWith('/versions/1'))
      return Response.json({
        ...template,
        key: ownerType.key,
        name: ownerType.name,
      });
    if (path === '/api/property/v1/communities')
      return Response.json({ items: [], total: 125, page: 1, page_size: 100 });
    if (path === base)
      return Response.json({
        id: communityId,
        name: ownerBatch.scope.name,
        enabled: communityEnabled,
      });
    if (path === `${base}/houses` || path === `${base}/space-nodes`)
      return Response.json({ items: [], total: 0, page: 1, page_size: 20 });
    if (path === `${base}/space-nodes/${nodeId}`)
      return Response.json({
        id: nodeId,
        node_type: 'building',
        name: '停用楼栋',
        enabled: false,
        effective_enabled: false,
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
      return Response.json(current);
    if (path.endsWith('/rows'))
      return Response.json({
        items: [
          {
            id: batchId,
            row_no: 2,
            precheck_status: 'valid',
            planned_action: 'skip',
            raw_values: {},
            normalized_values: {},
            business_values: {
              house_label: '第一百零一个小区／A栋／0001',
              name: '张*',
              phone: '138****0001',
              owner_status: '停用',
              private_command: '内部登记命令',
            },
            issue_count: 0,
            execution_status: 'pending',
            result_code: null,
            result_message: null,
            result_at: null,
          },
        ],
        total: 1,
        page: 1,
        page_size: 20,
      });
  });
}

afterEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

it('opens owner imports without house creation permission and locks the whole filtered community', async () => {
  const fetcher = mockOwnerImports();
  renderRoutes(`${route}?space_node_id=${nodeId}&room_no=101`);
  const button = await screen.findByRole('button', { name: '导入业主登记' });
  await screen.findByText('停用楼栋');
  expect(button).toBeEnabled();
  expect(
    screen.queryByRole('button', { name: '批量导入' }),
  ).not.toBeInTheDocument();
  fireEvent.click(button);
  expect(
    await screen.findByText('范围已锁定：第一百零一个小区'),
  ).toBeInTheDocument();
  expect(screen.getByRole('combobox', { name: '导入小区' })).toBeDisabled();
  expect(screen.getByRole('combobox', { name: '范围类型' })).toBeDisabled();
  expect(screen.getByRole('combobox', { name: '导入类型' })).toBeDisabled();
  expect(screen.getByText('来源页面：房屋管理')).toBeInTheDocument();
  const create = screen.getByRole('button', {
    name: '创建草稿，下一步上传文件',
  });
  await waitFor(() => expect(create).toBeEnabled());
  fireEvent.click(create);
  await waitFor(() =>
    expect(
      fetcher.mock.calls.some(
        ([url, init]) =>
          String(url).endsWith('/import-batches') && init?.method === 'POST',
      ),
    ).toBe(true),
  );
  const submitted = fetcher.mock.calls.find(
    ([url, init]) =>
      String(url).endsWith('/import-batches') && init?.method === 'POST',
  )!;
  expect(JSON.parse(String(submitted[1]?.body))).toEqual({
    import_type: 'house_owners',
    template_version_no: 1,
    scope: { type: 'community', id: communityId },
    mode: 'create',
  });
});

it.each([
  'property.house_owner.create',
  'property.import.create',
  'property.import.read',
])('hides the owner import entry without %s', async (missing) => {
  mockOwnerImports({
    allowed: [...permissions, 'property.house.create'].filter(
      (permission) => permission !== missing,
    ),
  });
  renderRoutes(route);
  await screen.findByText('房屋档案');
  expect(
    screen.queryByRole('button', { name: '导入业主登记' }),
  ).not.toBeInTheDocument();
  if (missing === 'property.house_owner.create')
    expect(screen.getByRole('button', { name: '批量导入' })).toBeEnabled();
});

it('disables owner imports in a disabled community', async () => {
  mockOwnerImports({ communityEnabled: false });
  renderRoutes(route);
  await screen.findByText('小区已停用，可维护已有资料；启用小区后才能新增。');
  expect(screen.getByRole('button', { name: '导入业主登记' })).toBeDisabled();
});

it('renders only declared owner values and explains disabled registrations are skipped', async () => {
  mockOwnerImports();
  renderRoutes(`/property/imports/${batchId}`);
  expect(
    await screen.findByText('第一百零一个小区／A栋／0001'),
  ).toBeInTheDocument();
  expect(screen.getByText('张*')).toBeInTheDocument();
  expect(screen.getByText('138****0001')).toBeInTheDocument();
  expect(screen.getByText('停用')).toBeInTheDocument();
  expect(screen.queryByText('内部登记命令')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: '确认执行' }));
  const dialog = await screen.findByRole('dialog');
  expect(
    within(dialog).getByText(
      /同一房屋下已有同姓名、同规范化手机号的登记（含停用记录）将跳过/,
    ),
  ).toBeInTheDocument();
  expect(within(dialog).getByText(/停用记录不会自动启用/)).toBeInTheDocument();
});

it('keeps the owner confirmation notice without house read navigation', async () => {
  mockOwnerImports({
    allowed: permissions.filter(
      (permission) => permission !== 'property.house.read',
    ),
  });
  renderRoutes(`/property/imports/${batchId}`);
  fireEvent.click(await screen.findByRole('button', { name: '确认执行' }));
  expect(
    within(await screen.findByRole('dialog')).getByText(
      /本次在目标小区内仅新增业主登记/,
    ),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole('button', { name: '返回房屋管理' }),
  ).not.toBeInTheDocument();
});

it('invalidates owner, house and audit data before returning to the target housing list', async () => {
  const invalidate = vi.spyOn(QueryClient.prototype, 'invalidateQueries');
  const fetcher = mockOwnerImports({
    current: {
      ...ownerBatch,
      status: 'completed',
      phase: 'finished',
      confirmed_at: batch.created_at,
      finished_at: batch.updated_at,
      next_actions: [],
    },
  });
  renderRoutes(`/property/imports/${batchId}`);
  fireEvent.click(await screen.findByRole('button', { name: '返回房屋管理' }));
  await waitFor(() =>
    expect(screen.getByTestId('location')).toHaveTextContent(route),
  );
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ['house-owners'] });
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ['houses'] });
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ['audit'] });
  await waitFor(() =>
    expect(
      fetcher.mock.calls.some(
        ([url]) => new URL(String(url)).pathname === `${base}/houses`,
      ),
    ).toBe(true),
  );
});
