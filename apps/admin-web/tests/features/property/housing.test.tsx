import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { renderRoutes } from '../../app/platform-harness';
import type { SessionResponse } from '@/shared/api/admin';
import type { Community } from '@/shared/api/property';
import type {
  House,
  HouseOwner,
  SpaceNode,
} from '@/features/property/housing/api';

const communityId = '019a0000-0000-7000-8000-000000000001';
const nodeId = '019a0000-0000-7000-8000-000000000002';
const houseId = '019a0000-0000-7000-8000-000000000003';
const timestamp = '2026-10-15T00:00:00Z';
const base = `/api/property/v1/communities/${communityId}`;
const route = `/property/communities/${communityId}/houses`;
const community: Community = {
  id: communityId,
  name: '春日小区',
  code: 'SPRING',
  property_company_id: communityId,
  property_company_name: '春日物业',
  address: '小区地址',
  enabled: true,
  created_at: timestamp,
  updated_at: timestamp,
};
const otherCommunity: Community = {
  ...community,
  id: '019a0000-0000-7000-8000-000000000005',
  name: '秋日小区',
  code: 'AUTUMN',
  enabled: false,
};
const otherBase = `/api/property/v1/communities/${otherCommunity.id}`;
const node: SpaceNode = {
  id: nodeId,
  community_id: communityId,
  parent_id: null,
  node_type: 'building',
  name: '一号楼',
  external_code: null,
  sort_order: 0,
  enabled: true,
  effective_enabled: true,
  has_children: true,
  ancestors: [],
  created_at: timestamp,
  updated_at: timestamp,
};
const house: House = {
  id: houseId,
  community_id: communityId,
  space_node_id: nodeId,
  room_no: '101',
  floor_no: 1,
  external_code: '001A',
  display_address: '春日小区／一号楼／101',
  enabled: true,
  effective_enabled: true,
  created_at: timestamp,
  updated_at: timestamp,
};
const owner: HouseOwner = {
  id: '019a0000-0000-7000-8000-000000000004',
  house_id: houseId,
  name: '原业主',
  phone: '13800000000',
  enabled: true,
  effective_enabled: true,
  created_at: timestamp,
  updated_at: timestamp,
};
const permissions = [
  'property.community.read',
  'property.space.read',
  'property.space.create',
  'property.space.update',
  'property.house.read',
  'property.house.create',
  'property.house.update',
  'property.house_owner.read',
  'property.house_owner.create',
  'property.house_owner.update',
];
const session: SessionResponse = {
  scope: 'property_admin',
  subject_id: '019a0000-0000-7000-8000-000000000005',
  login_name: 'property',
  display_name: '物业管理员',
  permissions,
  must_change_password: false,
  csrf_token: 'housing-csrf',
};

function mockHousing(
  allowed = permissions,
  conflict = false,
  availableCommunities?: Community[],
) {
  let houses = [{ ...house }];
  let owners = [{ ...owner }];
  let nodes = [{ ...node }];
  const page = <T,>(items: T[], target: URL, total = items.length) =>
    Response.json({
      items,
      total,
      page: Number(target.searchParams.get('page') || 1),
      page_size: Number(target.searchParams.get('page_size') || 20),
    });
  const fetcher = vi.fn<typeof fetch>(async (url, init) => {
    const target = new URL(String(url), window.location.origin);
    const path = target.pathname;
    const data = init?.body ? JSON.parse(String(init.body)) : {};
    if (path.endsWith('/admin-sessions/current'))
      return Response.json({ ...session, permissions: allowed });
    if (path === '/api/property/v1/communities') {
      const name = target.searchParams.get('name');
      if (availableCommunities)
        return page(
          availableCommunities.filter(
            (item) => !name || item.name.includes(name),
          ),
          target,
        );
      if (name)
        return page(
          [community, otherCommunity].filter((item) =>
            item.name.includes(name),
          ),
          target,
        );
      return page(
        target.searchParams.get('page') === '2'
          ? [otherCommunity]
          : [community],
        target,
        101,
      );
    }
    if (path === base) return Response.json(community);
    if (path === otherBase) return Response.json(otherCommunity);
    if (path === `${otherBase}/space-nodes`)
      return page(
        [
          {
            ...node,
            id: '019a0000-0000-7000-8000-000000000006',
            community_id: otherCommunity.id,
            name: '秋日楼栋',
            effective_enabled: false,
            has_children: false,
          },
        ],
        target,
      );
    if (path === `${otherBase}/houses`)
      return page(
        [
          {
            ...house,
            community_id: otherCommunity.id,
            room_no: '201',
            display_address: '秋日小区／秋日楼栋／201',
            effective_enabled: false,
          },
        ],
        target,
      );
    if (path === `${base}/space-nodes`) {
      if (init?.method === 'POST') {
        nodes = [...nodes, { ...node, id: 'new-node', ...data }];
        return Response.json(nodes.at(-1), { status: 201 });
      }
      if (target.searchParams.get('parent_id'))
        return page(
          [
            {
              ...node,
              id: 'unit',
              parent_id: nodeId,
              node_type: 'unit',
              name:
                target.searchParams.get('parent_id') === 'second'
                  ? '二号楼单元'
                  : '一单元',
              has_children: false,
              ancestors: [node],
            },
          ],
          target,
          target.searchParams.get('parent_id') === 'second' ? 21 : 1,
        );
      return page(
        target.searchParams.get('page') === '2'
          ? [{ ...node, id: 'second', name: '二号楼' }]
          : nodes,
        target,
        21,
      );
    }
    if (path === `${base}/space-nodes/${nodeId}`) {
      if (init?.method === 'PATCH')
        nodes = nodes.map((item) =>
          item.id === nodeId
            ? {
                ...item,
                ...data,
                effective_enabled: data.enabled ?? item.enabled,
              }
            : item,
        );
      return Response.json(nodes[0]);
    }
    if (path === `${base}/houses`) {
      if (init?.method === 'POST') {
        if (conflict)
          return Response.json(
            {
              type: 'urn:problem:property.duplicate_room_no',
              title: '房号重复',
              detail: '房号重复',
              code: 'property.duplicate_room_no',
              status: 409,
              instance: 'urn:request:conflict',
              request_id: 'conflict',
            },
            {
              status: 409,
              headers: { 'Content-Type': 'application/problem+json' },
            },
          );
        houses = [
          ...houses,
          { ...house, id: 'new-house', room_no: data.room_no },
        ];
        return Response.json(houses.at(-1), { status: 201 });
      }
      return page(houses, target);
    }
    if (path === `${base}/houses/${houseId}`) {
      if (init?.method === 'PATCH')
        houses = [
          {
            ...houses[0],
            ...data,
            effective_enabled: data.enabled ?? houses[0].enabled,
          },
        ];
      return Response.json(houses[0]);
    }
    if (path === `${base}/houses/${houseId}/owners`) {
      if (init?.method === 'POST') {
        owners = [...owners, { ...owner, id: 'new-owner', ...data }];
        return Response.json(owners.at(-1), { status: 201 });
      }
      return page(owners, target);
    }
    if (path === `${base}/houses/${houseId}/owners/${owner.id}`) {
      if (init?.method === 'PATCH')
        owners = owners.map((item) =>
          item.id === owner.id ? { ...item, ...data } : item,
        );
      return Response.json(owners[0]);
    }
    throw new Error(`Unexpected housing request: ${path}`);
  });
  vi.stubGlobal('fetch', fetcher);
  return fetcher;
}
afterEach(() => vi.unstubAllGlobals());

describe('property housing', () => {
  it.each([
    ['localhost', '/property/houses', route],
    ['property.xlife.test', '/houses', `/communities/${communityId}/houses`],
  ])(
    'automatically loads the only community on %s',
    async (host, entry, selectedPath) => {
      mockHousing(permissions, false, [community]);
      renderRoutes(entry, host);
      expect(
        await screen.findByText(house.display_address),
      ).toBeInTheDocument();
      expect(screen.getByText('春日小区（SPRING）')).toBeInTheDocument();
      expect(screen.getByTestId('location').textContent).toBe(selectedPath);
    },
  );

  it('keeps a single search result unselected when the company has multiple communities', async () => {
    const fetcher = mockHousing();
    renderRoutes('/property/houses');
    const picker = await screen.findByRole('combobox', { name: '当前小区' });
    fireEvent.mouseDown(picker);
    fireEvent.change(picker, { target: { value: '秋日' } });
    expect(
      await screen.findByText('秋日小区（AUTUMN） · 停用'),
    ).toBeInTheDocument();
    expect(screen.getByTestId('location').textContent).toBe('/property/houses');
    expect(
      fetcher.mock.calls.some(([url]) =>
        new URL(String(url), window.location.origin).pathname.endsWith(
          '/houses',
        ),
      ),
    ).toBe(false);
    fireEvent.click(screen.getByText('秋日小区（AUTUMN） · 停用'));
    expect(
      await screen.findByText('秋日小区／秋日楼栋／201'),
    ).toBeInTheDocument();
  });

  it.each([
    ['localhost', '/property/houses', '/property'],
    ['property.xlife.test', '/houses', ''],
  ])(
    'opens the standalone flat menu and keeps it selected on %s',
    async (host, entry, prefix) => {
      const fetcher = mockHousing();
      renderRoutes(entry, host);
      expect(
        await screen.findByText('请先选择小区，查看和维护房屋资料'),
      ).toBeInTheDocument();
      const menu = within(screen.getByRole('menu'));
      expect(menu.getAllByRole('menuitem')).toHaveLength(3);
      expect(menu.getByRole('link', { name: /工作台/ })).toHaveAttribute(
        'href',
        prefix || '/',
      );
      expect(menu.getByRole('link', { name: '小区查询' })).toHaveAttribute(
        'href',
        `${prefix}/communities`,
      );
      expect(menu.getByRole('link', { name: '房屋管理' })).toHaveAttribute(
        'href',
        entry,
      );
      expect(menu.queryByText('物业管理')).not.toBeInTheDocument();
      expect(
        fetcher.mock.calls.some(([url]) =>
          String(url).includes(`${communityId}/`),
        ),
      ).toBe(false);
      fireEvent.mouseDown(screen.getByRole('combobox', { name: '当前小区' }));
      fireEvent.click(await screen.findByText('春日小区（SPRING）'));
      expect(
        await screen.findByText(house.display_address),
      ).toBeInTheDocument();
      expect(screen.getByTestId('location').textContent).toBe(
        `${prefix}/communities/${communityId}/houses`,
      );
      expect(menu.getByRole('menuitem', { name: '房屋管理' })).toHaveClass(
        'ant-menu-item-selected',
      );
      fireEvent.click(screen.getByRole('link', { name: '房屋详情' }));
      expect(
        await screen.findByRole('link', { name: '返回房屋列表' }),
      ).toHaveAttribute('href', `${prefix}/communities/${communityId}/houses`);
      expect(menu.getByRole('menuitem', { name: '房屋管理' })).toHaveClass(
        'ant-menu-item-selected',
      );
    },
  );

  it('switches communities and resets the previous space, filters and page', async () => {
    const fetcher = mockHousing();
    renderRoutes(
      `${route}?space_node_id=${nodeId}&room_no=101&external_code=001A&floor_no=1&enabled=true&sort=created_at&page=2&page_size=5`,
    );
    await screen.findByText(house.display_address);
    await screen.findByText('一单元');
    const picker = screen.getByRole('combobox', { name: '当前小区' });
    fireEvent.mouseDown(picker);
    fireEvent.click(
      await screen.findByRole('button', { name: '加载更多小区' }),
    );
    fireEvent.click(await screen.findByText('秋日小区（AUTUMN） · 停用'));
    expect(
      await screen.findByText('秋日小区／秋日楼栋／201'),
    ).toBeInTheDocument();
    expect(screen.queryByText(house.display_address)).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: '一号楼' }),
    ).not.toBeInTheDocument();
    expect(screen.getByTestId('location').textContent).toBe(
      `/property/communities/${otherCommunity.id}/houses`,
    );
    expect(screen.getByLabelText('房号')).toHaveValue('');
    expect(
      await screen.findByText(
        '小区已停用，可维护已有资料；启用小区后才能新增。',
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '新增房屋' })).toBeDisabled();
    const requests = fetcher.mock.calls
      .map(([url]) => new URL(String(url), window.location.origin))
      .filter((url) => url.pathname.startsWith(otherBase));
    const houses = requests.find(
      (url) => url.pathname === `${otherBase}/houses`,
    )!;
    expect(Object.fromEntries(houses.searchParams)).toEqual({
      page: '1',
      page_size: '20',
      sort: '-created_at',
    });
    expect(requests.some((url) => url.pathname.includes(nodeId))).toBe(false);
  });

  it('searches community options on the server and shows the selected community on a deep link', async () => {
    const fetcher = mockHousing();
    renderRoutes(`/property/communities/${otherCommunity.id}/houses`);
    expect(
      await screen.findByText('秋日小区（AUTUMN） · 停用'),
    ).toBeInTheDocument();
    const picker = screen.getByRole('combobox', { name: '当前小区' });
    fireEvent.mouseDown(picker);
    fireEvent.change(picker, { target: { value: '春日' } });
    fireEvent.click(await screen.findByText('春日小区（SPRING）'));
    expect(await screen.findByText(house.display_address)).toBeInTheDocument();
    expect(
      fetcher.mock.calls.some(([url]) => {
        const target = new URL(String(url), window.location.origin);
        return (
          target.pathname === '/api/property/v1/communities' &&
          target.searchParams.get('name') === '春日'
        );
      }),
    ).toBe(true);
  });

  it('selects a building when creating from the community and omits unpermitted owners', async () => {
    const fetcher = mockHousing([
      'property.house.read',
      'property.house.create',
      'property.space.read',
    ]);
    renderRoutes(route);
    await screen.findByText(house.display_address);
    expect(
      screen.queryByRole('combobox', { name: '当前小区' }),
    ).not.toBeInTheDocument();
    expect(
      fetcher.mock.calls.some(([url]) => {
        const target = new URL(String(url), window.location.origin);
        return (
          target.pathname === '/api/property/v1/communities' ||
          target.pathname === base
        );
      }),
    ).toBe(false);
    fireEvent.click(screen.getByRole('button', { name: '新增房屋' }));
    const editor = within(await screen.findByRole('dialog'));
    expect(
      editor.queryByRole('button', { name: '添加业主' }),
    ).not.toBeInTheDocument();
    fireEvent.click(editor.getByRole('button', { name: '一号楼' }));
    fireEvent.change(editor.getByLabelText('房号'), {
      target: { value: '103' },
    });
    fireEvent.click(editor.getByRole('button', { name: '保 存' }));
    expect(await screen.findByText('103')).toBeInTheDocument();
    const write = fetcher.mock.calls.find(
      ([, init]) => init?.method === 'POST',
    )!;
    expect(JSON.parse(String(write[1]?.body))).toMatchObject({
      space_node_id: nodeId,
      room_no: '103',
    });
    expect(JSON.parse(String(write[1]?.body))).not.toHaveProperty('owners');
  });

  it('creates the permitted child type under the selected building and refreshes the tree', async () => {
    const fetcher = mockHousing();
    renderRoutes(`${route}?space_node_id=${nodeId}`);
    await screen.findByText(house.display_address);
    await waitFor(() =>
      expect(screen.getByRole('button', { name: '新增空间' })).toBeEnabled(),
    );
    fireEvent.click(screen.getByRole('button', { name: '新增空间' }));
    const editor = within(await screen.findByRole('dialog'));
    expect(editor.getByText('单元')).toBeInTheDocument();
    fireEvent.change(editor.getByLabelText('空间名称'), {
      target: { value: '二单元' },
    });
    fireEvent.click(editor.getByRole('button', { name: '保 存' }));
    await waitFor(() =>
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument(),
    );
    const write = fetcher.mock.calls.find(
      ([, init]) => init?.method === 'POST',
    )!;
    expect(JSON.parse(String(write[1]?.body))).toMatchObject({
      parent_id: nodeId,
      node_type: 'unit',
      name: '二单元',
    });
    expect(
      fetcher.mock.calls.filter(
        ([url, init]) => String(url).includes('/space-nodes?') && !init?.method,
      ).length,
    ).toBeGreaterThan(2);
  });

  it('restores the selected node, loads tree pages and puts exact filters in the URL', async () => {
    const fetcher = mockHousing(permissions, false, [community]);
    renderRoutes(
      `${route}?space_node_id=${nodeId}&floor_no=-1&external_code=001A`,
    );
    expect(await screen.findByText(house.display_address)).toBeInTheDocument();
    expect(await screen.findByText('一单元')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '加载更多空间' }));
    expect(await screen.findByText('二号楼')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '展开二号楼' }));
    expect(await screen.findByText('二号楼单元')).toBeInTheDocument();
    expect(
      await screen.findByRole('button', { name: '加载更多空间' }),
    ).toBeInTheDocument();
    expect(
      fetcher.mock.calls.some(([url]) => {
        const query = new URL(String(url), window.location.origin).searchParams;
        return query.get('parent_id') === 'second' && query.get('page') === '2';
      }),
    ).toBe(false);
    fireEvent.change(screen.getByLabelText('房号'), {
      target: { value: 'B01' },
    });
    fireEvent.click(screen.getByRole('button', { name: '查 询' }));
    await waitFor(() =>
      expect(screen.getByTestId('location').textContent).toContain(
        'room_no=B01',
      ),
    );
    const calls = fetcher.mock.calls.map(
      ([url]) => new URL(String(url), window.location.origin),
    );
    expect(
      calls.some(
        (url) =>
          url.searchParams.get('space_node_id') === nodeId &&
          url.searchParams.get('floor_no') === '-1',
      ),
    ).toBe(true);
    expect(
      calls.every((url) => url.pathname.startsWith('/api/property/')),
    ).toBe(true);
    expect(calls.some((url) => url.pathname.endsWith('/owners'))).toBe(false);
  });

  it('creates a house and its initial owners in one request and refreshes the list', async () => {
    const fetcher = mockHousing();
    renderRoutes(`${route}?space_node_id=${nodeId}`);
    await screen.findByText(house.display_address);
    await waitFor(() =>
      expect(screen.getByRole('button', { name: '新增房屋' })).toBeEnabled(),
    );
    fireEvent.click(screen.getByRole('button', { name: '新增房屋' }));
    const editor = within(await screen.findByRole('dialog'));
    fireEvent.change(await editor.findByLabelText('房号'), {
      target: { value: '102' },
    });
    fireEvent.click(editor.getByRole('button', { name: '添加业主' }));
    fireEvent.change(editor.getByLabelText('业主姓名'), {
      target: { value: '新业主' },
    });
    fireEvent.change(editor.getByLabelText('手机号'), {
      target: { value: '+8613900000000' },
    });
    fireEvent.click(editor.getByRole('button', { name: '保 存' }));
    expect(await screen.findByText('102')).toBeInTheDocument();
    const creation = fetcher.mock.calls.find(
      ([url, init]) =>
        new URL(String(url), window.location.origin).pathname ===
          `${base}/houses` && init?.method === 'POST',
    )!;
    expect(JSON.parse(String(creation[1]?.body))).toMatchObject({
      space_node_id: nodeId,
      room_no: '102',
      owners: [{ name: '新业主', phone: '+8613900000000' }],
    });
    expect(new Headers(creation[1]?.headers).get('X-CSRF-Token')).toBe(
      'housing-csrf',
    );
    expect(screen.getByTestId('location').textContent).not.toContain(
      '13900000000',
    );
    expect(
      fetcher.mock.calls.some(
        ([url, init]) =>
          String(url).endsWith('/owners') && init?.method === 'POST',
      ),
    ).toBe(false);
  });

  it('keeps inputs on a conflict, refreshes relevant data and never retries the write', async () => {
    const fetcher = mockHousing(permissions, true);
    renderRoutes(`${route}?space_node_id=${nodeId}`);
    await screen.findByText(house.display_address);
    await waitFor(() =>
      expect(screen.getByRole('button', { name: '新增房屋' })).toBeEnabled(),
    );
    fireEvent.click(screen.getByRole('button', { name: '新增房屋' }));
    const editor = within(await screen.findByRole('dialog'));
    fireEvent.change(await editor.findByLabelText('房号'), {
      target: { value: '101' },
    });
    fireEvent.click(editor.getByRole('button', { name: '保 存' }));
    expect(await editor.findByText('房号重复')).toBeInTheDocument();
    expect(await editor.findByLabelText('房号')).toHaveValue('101');
    expect(
      fetcher.mock.calls.filter(([, init]) => init?.method === 'POST'),
    ).toHaveLength(1);
  });

  it('does not request owner or space data without their separate read permissions', async () => {
    const fetcher = mockHousing([
      'property.house.read',
      'property.house.update',
    ]);
    renderRoutes(`${route}/${houseId}`);
    expect(await screen.findByText(house.display_address)).toBeInTheDocument();
    expect(screen.getByText('没有业主资料读取权限。')).toBeInTheDocument();
    expect(screen.queryByText(owner.phone)).not.toBeInTheDocument();
    expect(
      fetcher.mock.calls.some(([url]) =>
        /owners|space-nodes/.test(String(url)),
      ),
    ).toBe(false);
  });

  it('corrects owner data separately and confirms house status changes', async () => {
    const fetcher = mockHousing();
    renderRoutes(`${route}/${houseId}`);
    expect(await screen.findByText(owner.phone)).toBeInTheDocument();
    const ownersRequest = fetcher.mock.calls.find(([url]) =>
      new URL(String(url), window.location.origin).pathname.endsWith('/owners'),
    )!;
    expect(ownersRequest[1]?.cache).toBe('no-store');
    fireEvent.click(screen.getByRole('button', { name: '编辑业主' }));
    const editor = within(await screen.findByRole('dialog'));
    fireEvent.change(editor.getByLabelText('业主姓名'), {
      target: { value: '纠正姓名' },
    });
    fireEvent.click(editor.getByRole('button', { name: '保 存' }));
    expect(await screen.findByText('纠正姓名')).toBeInTheDocument();
    expect(
      fetcher.mock.calls.some(
        ([url, init]) =>
          String(url).endsWith(`/owners/${owner.id}`) &&
          init?.method === 'PATCH',
      ),
    ).toBe(true);
    fireEvent.click(screen.getAllByRole('button', { name: '停用' })[0]);
    const confirm = within(await screen.findByRole('dialog'));
    expect(confirm.getAllByText('停用房屋 101？').length).toBeGreaterThan(0);
    fireEvent.click(confirm.getByRole('button', { name: '确 定' }));
    await waitFor(() =>
      expect(
        fetcher.mock.calls.some(
          ([url, init]) =>
            String(url).endsWith(`/houses/${houseId}`) &&
            init?.method === 'PATCH',
        ),
      ).toBe(true),
    );
    expect(
      await screen.findByText(
        '房屋当前不可用，可修正已有资料；新增业主需要房屋及上级全部启用。',
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '新增业主' })).toBeDisabled();
  });

  it('guards dirty forms and blocks forbidden routes before business requests', async () => {
    mockHousing();
    const view = renderRoutes(`${route}?space_node_id=${nodeId}`);
    await screen.findByText(house.display_address);
    await waitFor(() =>
      expect(screen.getByRole('button', { name: '新增房屋' })).toBeEnabled(),
    );
    fireEvent.click(screen.getByRole('button', { name: '新增房屋' }));
    const editor = within(await screen.findByRole('dialog'));
    fireEvent.change(await editor.findByLabelText('房号'), {
      target: { value: '103' },
    });
    fireEvent.click(editor.getByRole('button', { name: '取 消' }));
    await waitFor(() =>
      expect(screen.getAllByText('放弃未保存的修改？').length).toBeGreaterThan(
        0,
      ),
    );
    view.unmount();
    const fetcher = mockHousing([]);
    renderRoutes(route);
    expect(await screen.findByText('无权访问此页面')).toBeInTheDocument();
    expect(
      fetcher.mock.calls.some(([url]) =>
        new URL(String(url), window.location.origin).pathname.startsWith(base),
      ),
    ).toBe(false);
  });
});
