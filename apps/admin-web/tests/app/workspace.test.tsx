import '@testing-library/jest-dom/vitest';
import { useState } from 'react';
import { ConfigProvider } from 'antd';
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
import { propertyPageAvailability } from '../../src/app/page-availability';
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
      <button
        onClick={() => {
          setNote('等待提交的备注');
          context.setDirty(true);
        }}
      >
        填写未保存备注
      </button>
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
  propertyPageAvailability.communities = false;
  propertyPageAvailability['payment-configuration'] = false;
  await act(async () => {
    await Promise.resolve();
  });
  vi.unstubAllGlobals();
  localStorage.clear();
  if (priorScroll)
    Object.defineProperty(HTMLElement.prototype, 'scrollTo', priorScroll);
  else Reflect.deleteProperty(HTMLElement.prototype, 'scrollTo');
});
function show(path: string, permissions = ['property.housing.read']) {
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
    if (path.endsWith('/v1/property-workspace/context'))
      return Promise.resolve(
        new Response(
          JSON.stringify({
            property_company_id: company.id,
            property_company_name: company.name,
          }),
          {
            headers: { 'Content-Type': 'application/json' },
          },
        ),
      );
    if (path.endsWith('/v1/community-options')) {
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
  render(
    <ConfigProvider theme={{ token: { motion: false } }}>
      <App />
    </ConfigProvider>,
  );
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
async function selectLastCommunity() {
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
}
async function switchToLastCommunity() {
  await selectLastCommunity();
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
        .filter((url) => url.pathname.endsWith('/v1/community-options'))
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
      localStorage.getItem('ezcmty-admin:property:' + subject + ':community'),
    ).toBe(lastCommunity);
    const nav = screen.getByRole('navigation', { name: '主导航' });
    fireEvent.click(within(nav).getByRole('button', { name: /工作概览/ }));
    await waitFor(() =>
      expect(screen.getByTestId('business-page')).toHaveTextContent('home'),
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
    expect(screen.getByText('公司范围 · 不受小区选择影响')).toBeInTheDocument();
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
  it('拥有读取权限时，关闭页面仍从菜单与命令搜索移除，小区上下文继续可用', async () => {
    show('/property/houses', [
      'property.housing.read',
      'property.payment.read',
    ]);
    await ready('houses');
    const nav = screen.getByRole('navigation', { name: '主导航' });
    expect(
      within(nav).queryByRole('button', { name: /小区资料|收款信息/ }),
    ).not.toBeInTheDocument();
    await switchToLastCommunity();
    fireEvent.click(screen.getByRole('button', { name: /搜索功能或操作/ }));
    const dialog = await screen.findByRole('dialog');
    expect(
      within(dialog).queryByRole('button', { name: /小区资料|收款信息/ }),
    ).not.toBeInTheDocument();
    const search = within(dialog).getByRole('textbox', {
      name: '搜索菜单、常用操作',
    });
    for (const term of ['小区资料', '收款信息']) {
      fireEvent.change(search, { target: { value: term } });
      expect(
        within(dialog).getByText('没有匹配的功能，请尝试业务名称'),
      ).toBeInTheDocument();
    }
  });
  it.each(['communities', 'payment-configuration'])(
    '物业直达关闭页面%s显示404，不挂载页面或执行其业务查询',
    async (page) => {
      const fetch = show('/property/' + page, ['property.payment.read']);
      expect(await screen.findByText('页面或记录不存在')).toBeInTheDocument();
      expect(screen.queryByTestId('business-page')).not.toBeInTheDocument();
      expect(
        fetch.mock.calls.map(([input]) => new URL(String(input)).pathname),
      ).toEqual(['/api/property/v1/admin-sessions/current']);
    },
  );
  it.each([
    ['communities', '小区资料'],
    ['payment-configuration', '收款信息'],
  ])('恢复%s开关后重新开放页面与菜单，另一页继续关闭', async (page, label) => {
    propertyPageAvailability[page] = true;
    show('/property/' + page, ['property.payment.read']);
    await ready(page);
    const nav = screen.getByRole('navigation', { name: '主导航' });
    expect(
      within(nav).getByRole('button', { name: new RegExp(label) }),
    ).toBeInTheDocument();
    expect(
      within(nav).queryByRole('button', {
        name: new RegExp(page === 'communities' ? '收款信息' : '小区资料'),
      }),
    ).not.toBeInTheDocument();
  });
  it.each([
    [
      '/platform/communities',
      'platform-communities',
      'platform.onboarding.read',
    ],
    [
      '/platform/companies/' + company.id + '/payment-configuration',
      'payment-configuration',
      'platform.payment_config.read',
    ],
  ])('物业页面开关不影响平台地址%s', async (path, page, permission) => {
    show(path, [permission]);
    await waitFor(() =>
      expect(screen.getByTestId('business-page')).toHaveTextContent(page),
    );
    expect(screen.queryByText('页面或记录不存在')).not.toBeInTheDocument();
    expect(screen.getByText('平台管理范围')).toBeInTheDocument();
    expect(
      screen.queryByRole('combobox', { name: '当前小区' }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole('navigation', { name: '面包屑' }),
    ).toBeInTheDocument();
  });
  it('只读物业命令面板仅列出本端授权菜单，不暴露跨端或写操作', async () => {
    show('/property/houses', ['property.housing.read', 'property.bill.read']);
    await ready('houses');
    fireEvent.click(screen.getByRole('button', { name: /搜索功能或操作/ }));
    const dialog = await screen.findByRole('dialog');
    expect(
      within(dialog).getByRole('button', { name: /房屋档案/ }),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByRole('button', { name: /物业账单/ }),
    ).toBeInTheDocument();
    expect(
      within(dialog).queryByRole('button', {
        name: /账号管理|物业公司|角色权限|新增物业费账单|新建批量导入/,
      }),
    ).not.toBeInTheDocument();
    expect(within(dialog).getByText(/物业后台 · 锦绣华庭/)).toBeInTheDocument();
    fireEvent.change(
      within(dialog).getByRole('textbox', { name: '搜索菜单、常用操作' }),
      { target: { value: '管理员' } },
    );
    expect(
      within(dialog).getByText('没有匹配的功能，请尝试业务名称'),
    ).toBeInTheDocument();
  });
  it.each([
    ['房屋管理', '房屋档案', 'houses'],
    ['物业费账单', '物业账单', 'bills'],
  ])(
    '原名称%s可搜索到%s，并跳转到原业务页面',
    async (oldName, newName, page) => {
      show('/property/houses', ['property.housing.read', 'property.bill.read']);
      await ready('houses');
      fireEvent.click(screen.getByRole('button', { name: /搜索功能或操作/ }));
      const dialog = await screen.findByRole('dialog');
      fireEvent.change(
        within(dialog).getByRole('textbox', { name: '搜索菜单、常用操作' }),
        { target: { value: oldName } },
      );
      fireEvent.click(
        within(dialog).getByRole('button', { name: new RegExp(newName) }),
      );
      await ready(page);
      expect(window.location.pathname).toBe(
        `/property/communities/${firstCommunity}/${page}`,
      );
    },
  );
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
    expect(
      within(screen.getByRole('navigation', { name: '面包屑' })).getByText(
        '房屋详情',
      ),
    ).toHaveAttribute('aria-current', 'page');
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
  it.each(['面包屑导航', '切换小区'])(
    '%s先确认未保存内容，取消保留原页，确认后执行目标',
    async (action) => {
      show('/property/houses');
      await ready('houses');
      fireEvent.click(screen.getByRole('button', { name: '填写未保存备注' }));
      expect(screen.getByText(/有未保存内容/)).toBeInTheDocument();
      const leave = async () => {
        if (action === '切换小区') await selectLastCommunity();
        else
          fireEvent.click(
            within(
              screen.getByRole('navigation', { name: '面包屑' }),
            ).getByRole('button', { name: '工作概览' }),
          );
      };
      await leave();
      const dialog = await screen.findByRole('dialog');
      expect(dialog).toHaveTextContent('离开前放弃未保存的内容？');
      fireEvent.click(within(dialog).getByRole('button', { name: '继续编辑' }));
      await waitFor(() => expect(dialog).not.toBeInTheDocument());
      expect(window.location.pathname).toBe('/property/houses');
      expect(screen.getByTestId('business-page')).toHaveTextContent('houses');
      expect(screen.getByTestId('business-community')).toHaveTextContent(
        firstCommunity,
      );
      expect(screen.getByRole('textbox', { name: '临时查看备注' })).toHaveValue(
        '等待提交的备注',
      );
      expect(screen.getByText(/有未保存内容/)).toBeInTheDocument();
      await leave();
      fireEvent.click(
        within(await screen.findByRole('dialog')).getByRole('button', {
          name: '放弃并继续',
        }),
      );
      if (action === '切换小区') {
        await waitFor(() =>
          expect(screen.getByTestId('business-community')).toHaveTextContent(
            lastCommunity,
          ),
        );
        expect(window.location.pathname).toBe(
          '/property/communities/' + lastCommunity + '/houses',
        );
      } else {
        await waitFor(() =>
          expect(screen.getByTestId('business-page')).toHaveTextContent('home'),
        );
        expect(window.location.pathname).toBe('/property');
      }
      expect(screen.queryByText(/有未保存内容/)).not.toBeInTheDocument();
    },
  );
});
