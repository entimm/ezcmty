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
const nodeId = '019a0000-0000-7000-8000-000000000998';
const base = `/api/property/v1/communities/${communityId}`;
const route = `/property/communities/${communityId}/houses`;
const houseType: ImportType = {
  ...importType,
  key: 'houses',
  name: '房屋档案',
  allowed_scope_types: ['community'],
};
const permissions = [
  'property.house.read',
  'property.house.create',
  'property.import.read',
  'property.import.create',
  'property.import.execute',
  'property.space.read',
];
const houseBatch: Batch = {
  ...batch,
  import_type: 'houses',
  import_type_name: '房屋档案',
  template: { ...batch.template, key: 'houses' },
  scope: { type: 'community', id: communityId, name: '第一百零一个小区' },
  business_preview: {
    fields: [
      { key: 'house_label', label: '完整位置', format: 'text' },
      { key: 'room_no', label: '房号', format: 'text' },
      { key: 'floor_no', label: '楼层', format: 'text' },
      { key: 'external_code', label: '房屋外部编号', format: 'text' },
    ],
    summary: [],
  },
};

function mockHouses(allowed = permissions, current = houseBatch) {
  return mockImports('property_admin', allowed, (path, init) => {
    if (path.endsWith('/import-types'))
      return Response.json({ items: [houseType] });
    if (path.endsWith('/versions/1'))
      return Response.json({ ...template, key: 'houses', name: '房屋档案' });
    if (path === '/api/property/v1/communities')
      return Response.json({ items: [], total: 125, page: 1, page_size: 100 });
    if (path === base)
      return Response.json({
        id: communityId,
        name: houseBatch.scope.name,
        enabled: true,
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
            planned_action: 'create',
            raw_values: {},
            normalized_values: {},
            business_values: {
              house_label: '第一百零一个小区／A栋／0001',
              room_no: '0001',
              floor_no: -1,
              external_code: '0001A',
              private_command: '内部建房命令',
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
  vi.unstubAllGlobals();
});

it('locks the whole community from a filtered house list and reads its name by ID', async () => {
  const fetcher = mockHouses();
  renderRoutes(`${route}?space_node_id=${nodeId}&room_no=101`);
  const button = await screen.findByRole('button', { name: '批量导入' });
  await screen.findByText('停用楼栋');
  expect(button).toBeEnabled();
  fireEvent.click(button);
  expect(
    await screen.findByText('范围已锁定：第一百零一个小区'),
  ).toBeInTheDocument();
  expect(screen.getByRole('combobox', { name: '导入小区' })).toBeDisabled();
  expect(screen.getByRole('combobox', { name: '导入类型' })).toBeDisabled();
  expect(screen.getByText('来源页面：房屋管理')).toBeInTheDocument();
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
  const submitted = fetcher.mock.calls.find(
    ([url, init]) =>
      String(url).endsWith('/import-batches') && init?.method === 'POST',
  )!;
  expect(JSON.parse(String(submitted[1]?.body))).toEqual({
    import_type: 'houses',
    template_version_no: 1,
    scope: { type: 'community', id: communityId },
    mode: 'create',
  });
});

it.each([
  'property.house.create',
  'property.import.create',
  'property.import.read',
])('hides the import entry without %s', async (missing) => {
  mockHouses(permissions.filter((permission) => permission !== missing));
  renderRoutes(route);
  await screen.findByText('房屋档案');
  expect(
    screen.queryByRole('button', { name: '批量导入' }),
  ).not.toBeInTheDocument();
});

it('shows safe housing values and the confirmed import limits', async () => {
  mockHouses();
  renderRoutes(`/property/imports/${batchId}`);
  expect(
    await screen.findByText('第一百零一个小区／A栋／0001'),
  ).toBeInTheDocument();
  expect(screen.getByText('0001A')).toBeInTheDocument();
  expect(screen.queryByText('内部建房命令')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: '确认执行' }));
  const dialog = await screen.findByRole('dialog');
  expect(
    within(dialog).getByText(/请提前建立分区、楼栋和单元，文件不携带业主信息/),
  ).toBeInTheDocument();
});

it('returns to the target housing list after import', async () => {
  const fetcher = mockHouses(permissions, {
    ...houseBatch,
    status: 'completed',
    phase: 'finished',
    confirmed_at: batch.created_at,
    finished_at: batch.updated_at,
    next_actions: [],
  });
  renderRoutes(`/property/imports/${batchId}`);
  fireEvent.click(await screen.findByRole('button', { name: '返回房屋管理' }));
  await waitFor(() =>
    expect(screen.getByTestId('location')).toHaveTextContent(route),
  );
  await waitFor(() =>
    expect(
      fetcher.mock.calls.some(
        ([url]) => new URL(String(url)).pathname === `${base}/houses`,
      ),
    ).toBe(true),
  );
});
