import '@testing-library/jest-dom/vitest';
import { useState } from 'react';
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import App from '../../src/app/App';
import { navigate, setNavigationGuard } from '../../src/app/navigation';
import { useAdmin } from '../../src/shared/context';
import { useResource } from '../../src/shared/hooks';
import type { SessionResponse } from '../../src/shared/types';

vi.mock('../../src/features/property/PropertyPages', () => ({
  PropertyPages: () => <WorkspaceProbe />,
}));
vi.mock('../../src/features/platform/PlatformPages', () => ({
  PlatformPages: () => <WorkspaceProbe />,
}));
vi.mock('../../src/features/property/imports', () => ({
  PropertyImportsPage: () => <WorkspaceProbe />,
}));
vi.mock('../../src/features/platform/imports', () => ({
  PlatformImportsPage: () => <WorkspaceProbe />,
}));
vi.mock('../../src/features/property/payments', () => ({
  PropertyPaymentsPage: () => <WorkspaceProbe />,
}));
vi.mock('../../src/features/platform/payments', () => ({
  PlatformPaymentsPage: () => <WorkspaceProbe />,
}));
vi.mock('../../src/app/Dashboard', () => ({
  Dashboard: () => <WorkspaceProbe />,
}));

const firstCommunity = '00000000-0000-4000-8000-000000000001';
const lastCommunity = '00000000-0000-4000-8000-000000000101';
const house = '00000000-0000-4000-8000-000000000201';
const subject = '00000000-0000-4000-8000-000000000301';
const company = {
  id: '00000000-0000-4000-8000-000000000401',
  code: 'WY001',
  name: '锦城物业',
  contact_name: '陈静',
  contact_phone: '13800138000',
  enabled: true,
  created_at: '2026-10-01T00:00:00Z',
  updated_at: '2026-10-01T00:00:00Z',
};
const communities = Array.from({ length: 101 }, (_, index) => ({
  id: '00000000-0000-4000-8000-' + String(index + 1).padStart(12, '0'),
  code: 'CM' + String(index + 1),
  name:
    index === 0
      ? '锦绣华庭'
      : index === 100
        ? '云栖花园'
        : '服务小区' + String(index + 1),
  property_company_id: company.id,
  property_company_name: company.name,
  address: '社区地址',
  enabled: true,
}));

function WorkspaceProbe() {
  const context = useAdmin();
  const [note, setNote] = useState('');
  const companyScope = [
    'company',
    'reconciliation',
    'payment-configuration',
    'home',
  ].includes(context.page);
  const dataScope = companyScope ? 'company' : context.communityId;
  const resource = useResource(
    ['workspace-probe', context.page, dataScope],
    () =>
      context.request<{ label: string }>(
        '/v1/workspace-probe?scope=' + encodeURIComponent(dataScope),
      ),
    !!dataScope || context.scope === 'platform',
  );
  return (
    <section>
      <output data-testid="business-page">{context.page}</output>
      <output data-testid="business-community">{context.communityId}</output>
      <output data-testid="business-community-count">
        {context.communities.length}
      </output>
      <output data-testid="business-query">
        {JSON.stringify(context.params)}
      </output>
      <output data-testid="business-result">
        {resource.data?.label || ''}
      </output>
      <label>
        临时查看备注
        <input value={note} onChange={(event) => setNote(event.target.value)} />
      </label>
      {context.page === 'houses' && (
        <button
          onClick={() =>
            context.go('house-detail', {
              community_id: context.communityId,
              house_id: house,
            })
          }
        >
          打开房屋详情
        </button>
      )}
      {context.page === 'house-detail' && (
        <button onClick={() => context.go('houses')}>返回房屋列表</button>
      )}
    </section>
  );
}
const priorScroll = Object.getOwnPropertyDescriptor(
  HTMLElement.prototype,
  'scrollTo',
);
beforeEach(() =>
  Object.defineProperty(HTMLElement.prototype, 'scrollTo', {
    configurable: true,
    value: vi.fn(),
  }),
);
afterEach(async () => {
  cleanup();
  setNavigationGuard();
  await act(async () => {
    await Promise.resolve();
  });
  vi.unstubAllGlobals();
  localStorage.clear();
  if (priorScroll)
    Object.defineProperty(HTMLElement.prototype, 'scrollTo', priorScroll);
  else Reflect.deleteProperty(HTMLElement.prototype, 'scrollTo');
});
function show(
  path: string,
  permissions = [
    'property.company.read',
    'property.community.read',
    'property.house.read',
  ],
) {
  localStorage.clear();
  const session: SessionResponse = {
    scope: path.startsWith('/platform') ? 'platform_admin' : 'property_admin',
    subject_id: subject,
    login_name: 'tester',
    display_name: '测试管理员',
    permissions,
    must_change_password: false,
    csrf_token: 'csrf-workspace',
  };
  const fetch = vi.fn<typeof globalThis.fetch>().mockImplementation((input) => {
    const url = new URL(String(input), window.location.href),
      path = url.pathname;
    if (path.endsWith('/v1/admin-sessions/current'))
      return Promise.resolve(
        new Response(JSON.stringify(session), {
          headers: { 'Content-Type': 'application/json' },
        }),
      );
    if (path.endsWith('/v1/property-companies/current'))
      return Promise.resolve(
        new Response(JSON.stringify(company), {
          headers: { 'Content-Type': 'application/json' },
        }),
      );
    if (path.endsWith('/v1/communities')) {
      const page = Number(url.searchParams.get('page')) || 1;
      const items = communities.slice((page - 1) * 100, page * 100);
      return Promise.resolve(
        new Response(
          JSON.stringify({
            items,
            total: communities.length,
            page,
            page_size: 100,
          }),
          { headers: { 'Content-Type': 'application/json' } },
        ),
      );
    }
    if (path.endsWith('/v1/workspace-probe'))
      return Promise.resolve(
        new Response(
          JSON.stringify({
            label: '业务范围：' + url.searchParams.get('scope'),
          }),
          { headers: { 'Content-Type': 'application/json' } },
        ),
      );
    return Promise.reject(new Error('未预期的接口：' + url.pathname));
  });
  vi.stubGlobal('fetch', fetch);
  act(() => navigate(path, true));
  render(<App />);
  return fetch;
}
async function ready(page: string) {
  await waitFor(() =>
    expect(screen.getByTestId('business-page')).toHaveTextContent(page),
  );
  await waitFor(() =>
    expect(screen.getByTestId('business-community-count')).toHaveTextContent(
      '101',
    ),
  );
}
async function switchToLastCommunity() {
  const combo = screen.getByRole('combobox', { name: '当前小区' });
  fireEvent.mouseDown(combo);
  fireEvent.change(combo, { target: { value: '云栖花园' } });
  await waitFor(() =>
    expect(
      screen.getByRole('option', { name: '云栖花园' }),
    ).toBeInTheDocument(),
  );
  fireEvent.click(
    screen.getByText('云栖花园', {
      selector: '.ant-select-item-option-content',
    }),
  );
  await waitFor(() =>
    expect(screen.getByTestId('business-community')).toHaveTextContent(
      lastCommunity,
    ),
  );
}

describe('工作空间完整组装', () => {
  it('真实身份恢复后才执行上下文和业务查询，完整读取超过一页的小区', async () => {
    const fetch = show('/property/houses');
    await ready('houses');
    await waitFor(() =>
      expect(screen.getByTestId('business-result')).toHaveTextContent(
        '业务范围：' + firstCommunity,
      ),
    );
    const urls = fetch.mock.calls.map(([input]) => new URL(String(input)));
    expect(urls[0].pathname).toBe('/api/property/v1/admin-sessions/current');
    expect(
      urls
        .filter((url) => url.pathname.endsWith('/v1/communities'))
        .map((url) => url.searchParams.get('page')),
    ).toEqual(['1', '2']);
    expect(urls.every((url) => url.pathname.startsWith('/api/property/'))).toBe(
      true,
    );
  });
  it('切换小区同步导航、持久选择与业务查询，其他页面共享当前选择', async () => {
    const fetch = show('/property/houses');
    await ready('houses');
    await switchToLastCommunity();
    await waitFor(() =>
      expect(screen.getByTestId('business-result')).toHaveTextContent(
        '业务范围：' + lastCommunity,
      ),
    );
    expect(window.location.pathname).toBe(
      '/property/communities/' + lastCommunity + '/houses',
    );
    expect(
      localStorage.getItem('xlife-admin:property:' + subject + ':community'),
    ).toBe(lastCommunity);
    const nav = screen.getByRole('navigation', { name: '主导航' });
    fireEvent.click(within(nav).getByRole('button', { name: /小区资料/ }));
    await waitFor(() =>
      expect(screen.getByTestId('business-page')).toHaveTextContent(
        'communities',
      ),
    );
    expect(screen.getByTestId('business-community')).toHaveTextContent(
      lastCommunity,
    );
    expect(
      fetch.mock.calls.some(([url]) => String(url).includes('/api/platform/')),
    ).toBe(false);
  });
  it('公司范围页面切换小区时保持公司范围和页面状态', async () => {
    show('/property/company');
    await ready('company');
    expect(
      screen.getByText('本页为本公司范围 · 不受小区选择影响'),
    ).toBeInTheDocument();
    fireEvent.change(screen.getByRole('textbox', { name: '临时查看备注' }), {
      target: { value: '查看公司整体资料' },
    });
    await switchToLastCommunity();
    expect(window.location.pathname).toBe('/property/company');
    expect(screen.getByTestId('business-result')).toHaveTextContent(
      '业务范围：company',
    );
    expect(screen.getByRole('textbox', { name: '临时查看备注' })).toHaveValue(
      '查看公司整体资料',
    );
  });
  it('只读物业命令面板仅列出本端授权菜单，不暴露跨端或写操作', async () => {
    show('/property/houses', [
      'property.company.read',
      'property.community.read',
      'property.house.read',
      'property.bill.read',
    ]);
    await ready('houses');
    fireEvent.click(screen.getByRole('button', { name: /搜索功能或操作/ }));
    const dialog = await screen.findByRole('dialog');
    expect(
      within(dialog).getByRole('button', { name: /房屋管理/ }),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByRole('button', { name: /物业费账单/ }),
    ).toBeInTheDocument();
    expect(
      within(dialog).queryByRole('button', {
        name: /管理员|物业公司|角色与权限|新增物业费账单|新建批量导入/,
      }),
    ).not.toBeInTheDocument();
    expect(within(dialog).getByText(/物业后台 · 锦绣华庭/)).toBeInTheDocument();
  });
  it('从列表进详情再返回，恢复筛选、分页和同一小区', async () => {
    show(
      '/property/communities/' +
        firstCommunity +
        '/houses?search=1%E5%B9%A2&page=3&enabled=true',
    );
    await ready('houses');
    fireEvent.click(screen.getByRole('button', { name: '打开房屋详情' }));
    await waitFor(() =>
      expect(screen.getByTestId('business-page')).toHaveTextContent(
        'house-detail',
      ),
    );
    expect(window.location.pathname).toBe(
      '/property/communities/' + firstCommunity + '/houses/' + house,
    );
    fireEvent.click(screen.getByRole('button', { name: '返回房屋列表' }));
    await waitFor(() =>
      expect(screen.getByTestId('business-page')).toHaveTextContent('houses'),
    );
    const query = new URLSearchParams(window.location.search);
    expect(query.get('search')).toBe('1幢');
    expect(query.get('page')).toBe('3');
    expect(query.get('enabled')).toBe('true');
    expect(window.location.pathname).toBe(
      '/property/communities/' + firstCommunity + '/houses',
    );
  });
});
