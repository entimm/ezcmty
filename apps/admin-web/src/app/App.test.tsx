import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import type { ReactElement } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import App from './App';
import configuredRoutes from '../../config/routes';
import { patchClientRoutes, rootContainer } from '../app';
import PlatformApp from './platform/PlatformApp';
import PlatformHome from './platform/HomePage';
import PropertyApp from './property/PropertyApp';
import PropertyHome from './property/HomePage';
import NotFoundPage from '../components/NotFoundPage';
import LoginPage from '../features/admin/auth/LoginPage';
import ChangePasswordPage from '../features/admin/auth/ChangePasswordPage';
import ProfilePage from '../features/admin/profile/ProfilePage';
import AccountsPage from '../features/admin/accounts/AccountsPage';
import RolesPage from '../features/admin/roles/RolesPage';
import AuditPage from '../features/admin/audit/AuditPage';
import CompaniesPage from '../features/admin/property/CompaniesPage';
import CompanyDetailPage from '../features/admin/property/CompanyDetailPage';
import CommunitiesPage from '../features/admin/property/CommunitiesPage';
import WorkspaceCommunitiesPage from '../features/admin/property/WorkspaceCommunitiesPage';
import type { SessionResponse } from '../shared/admin-api';
import { safeReturnTarget } from './admin-routes';

const pages = {
  '@/app/App': App,
  '@/app/platform/PlatformApp': PlatformApp,
  '@/app/platform/HomePage': PlatformHome,
  '@/app/property/PropertyApp': PropertyApp,
  '@/app/property/HomePage': PropertyHome,
  '@/components/NotFoundPage': NotFoundPage,
  '@/features/admin/auth/LoginPage': LoginPage,
  '@/features/admin/auth/ChangePasswordPage': ChangePasswordPage,
  '@/features/admin/profile/ProfilePage': ProfilePage,
  '@/features/admin/accounts/AccountsPage': AccountsPage,
  '@/features/admin/roles/RolesPage': RolesPage,
  '@/features/admin/audit/AuditPage': AuditPage,
  '@/features/admin/property/CompaniesPage': CompaniesPage,
  '@/features/admin/property/CompanyDetailPage': CompanyDetailPage,
  '@/features/admin/property/CommunitiesPage': CommunitiesPage,
  '@/features/admin/property/WorkspaceCommunitiesPage':
    WorkspaceCommunitiesPage,
};
const session: SessionResponse = {
  scope: 'platform_admin',
  subject_id: 'root',
  login_name: 'root',
  display_name: '测试管理员',
  must_change_password: false,
  csrf_token: 'csrf-token',
  permissions: [
    'admin.account.read',
    'admin.account.create',
    'admin.account.update',
    'admin.account.assign_roles',
    'admin.account.reset_password',
    'admin.role.read',
    'admin.role.create',
    'admin.role.update',
    'admin.role.assign_permissions',
    'admin.audit.read',
    'property.company.read',
    'property.company.create',
    'property.company.update',
    'property.community.read',
    'property.community.create',
    'property.community.update',
    'property.admin.read',
    'property.admin.create',
    'property.admin.update',
    'property.admin.reset_password',
  ],
};
const account = {
  id: 'member',
  scope: 'platform_admin',
  login_name: 'member',
  display_name: '成员',
  enabled: true,
  must_change_password: false,
  created_at: '2026-10-14T00:00:00Z',
  roles: [],
};
const role = {
  id: 'reader',
  code: 'reader',
  name: '查询角色',
  enabled: true,
  is_system: false,
  permissions: ['admin.account.read'],
};
const companyId = '019a0000-0000-7000-8000-000000000001';
const company = {
  id: companyId,
  code: 'TEST',
  name: '测试物业公司',
  contact_name: '联系人',
  contact_phone: null,
  enabled: false,
  created_at: '2026-10-14T00:00:00Z',
  updated_at: '2026-10-14T00:00:00Z',
};
const community = {
  id: '019a0000-0000-7000-8000-000000000002',
  property_company_id: companyId,
  property_company_name: company.name,
  code: 'COMMUNITY',
  name: '测试小区',
  address: '测试地址',
  enabled: true,
  created_at: company.created_at,
  updated_at: company.updated_at,
};
const propertyAdmin = {
  ...account,
  id: '019a0000-0000-7000-8000-000000000003',
  scope: 'property_admin',
  property_company_id: companyId,
  display_name: '公司管理人员',
};
const propertySession: SessionResponse = {
  ...session,
  scope: 'property_admin',
  subject_id: propertyAdmin.id,
  login_name: 'property_root',
  display_name: propertyAdmin.display_name,
  permissions: ['property.company.read', 'property.community.read'],
};
function mockApi(
  identity: SessionResponse | null = session,
  propertyIdentity: SessionResponse | null = propertySession,
) {
  const fetcher = vi.fn<typeof fetch>(async (url, init) => {
    const path = new URL(String(url), window.location.origin).pathname;
    const isProperty = path.startsWith('/api/property/');
    const currentIdentity = isProperty ? propertyIdentity : identity;
    if (path.endsWith('/admin-sessions/current'))
      return currentIdentity
        ? Response.json(currentIdentity)
        : new Response(null, { status: 401 });
    if (path.endsWith('/admin-sessions') && init?.method === 'POST')
      return Response.json(isProperty ? propertySession : session, {
        status: 201,
      });
    if (path.endsWith('/property-companies/current'))
      return Response.json({ ...company, enabled: true });
    if (path.endsWith('/admin-accounts/me'))
      return Response.json({
        id: currentIdentity?.subject_id,
        scope: currentIdentity?.scope,
        login_name: currentIdentity?.login_name,
        display_name: currentIdentity?.display_name,
      });
    if (path.endsWith('/admin-accounts/member')) return Response.json(account);
    if (path.endsWith('/admin-roles/reader')) return Response.json(role);
    if (path.endsWith('/admin-permissions'))
      return Response.json([
        {
          code: 'admin.account.read',
          name: '查看管理员',
          group: '管理员',
          assignable: true,
        },
      ]);
    if (
      path.endsWith(
        `/property-companies/${companyId}/admin-accounts/${propertyAdmin.id}/password-resets`,
      )
    )
      return new Response(null, { status: 204 });
    if (
      path.endsWith(
        `/property-companies/${companyId}/admin-accounts/${propertyAdmin.id}`,
      )
    )
      return Response.json(propertyAdmin);
    if (path.endsWith(`/property-companies/${companyId}/admin-accounts`))
      return init?.method === 'POST'
        ? Response.json(propertyAdmin, { status: 201 })
        : Response.json({
            items: [propertyAdmin],
            total: 1,
            page: 1,
            page_size: 20,
          });
    if (path.endsWith(`/property-companies/${companyId}`))
      return Response.json(company);
    if (path.endsWith('/property-companies'))
      return init?.method === 'POST'
        ? Response.json(company, { status: 201 })
        : Response.json({ items: [company], total: 1, page: 1, page_size: 20 });
    if (path.endsWith(`/communities/${community.id}`))
      return Response.json(community);
    if (path.endsWith('/communities'))
      return init?.method === 'POST'
        ? Response.json(community, { status: 201 })
        : Response.json({
            items: [community],
            total: 1,
            page: 1,
            page_size: 20,
          });
    if (path.endsWith('/admin-accounts')) {
      if (init?.method === 'POST')
        return Response.json(account, { status: 201 });
      return Response.json({
        items: [account],
        total: 1,
        page: 1,
        page_size: 20,
      });
    }
    if (path.endsWith('/admin-roles'))
      return Response.json({ items: [role], total: 1, page: 1, page_size: 20 });
    if (path.endsWith('/admin-audit-logs'))
      return Response.json({ items: [], total: 0, page: 1, page_size: 20 });
    return new Response(null, { status: 204 });
  });
  vi.stubGlobal('fetch', fetcher);
  return fetcher;
}
beforeEach(() => mockApi());
afterEach(() => vi.unstubAllGlobals());
interface ConfiguredRoute {
  path: string;
  component: string;
  routes?: ConfiguredRoute[];
  children?: ConfiguredRoute[];
}
function routeElements(routes: ConfiguredRoute[]): ReactElement[] {
  return routes.map((route) => {
    const Page = pages[route.component as keyof typeof pages];
    return (
      <Route key={route.path} path={route.path} element={<Page />}>
        {route.children && routeElements(route.children)}
      </Route>
    );
  });
}
function LocationProbe() {
  const location = useLocation();
  return (
    <output data-testid="location">
      {location.pathname}
      {location.search}
    </output>
  );
}
function renderRoutes(path: string, hostname?: string) {
  if (hostname) {
    const location = new URL(`http://${hostname}:8080`);
    vi.stubGlobal(
      'window',
      new Proxy(window, {
        get: (target, key) =>
          key === 'location' ? location : Reflect.get(target, key, target),
      }),
    );
  }
  function copyRoutes(routes: ConfiguredRoute[]): ConfiguredRoute[] {
    return routes.map(({ routes: children, ...route }) => ({
      ...route,
      children: children && copyRoutes(children),
    }));
  }
  const routes = copyRoutes(configuredRoutes);
  patchClientRoutes({ routes });
  return render(
    rootContainer(
      <MemoryRouter initialEntries={[path]}>
        <LocationProbe />
        <Routes>{routeElements(routes)}</Routes>
      </MemoryRouter>,
    ),
  );
}
describe('domain navigation and identity', () => {
  it.each([
    ['platform.xlife.test', '平台管理 · 登录', '/api/platform/'],
    ['property.xlife.test', '物业管理 · 登录', '/api/property/'],
  ])('opens only its own login from %s root', async (host, title, apiBase) => {
    const fetcher = mockApi(null, null);
    renderRoutes('/', host);
    expect(await screen.findByText(title)).toBeInTheDocument();
    expect(screen.getByTestId('location')).toHaveTextContent(
      '/login?return_to=%2F',
    );
    expect(screen.queryByText('进入平台管理端')).not.toBeInTheDocument();
    expect(
      fetcher.mock.calls.every(([url]) =>
        new URL(String(url)).pathname.startsWith(apiBase),
      ),
    ).toBe(true);
  });

  it('returns to a clean protected URL after login', async () => {
    mockApi(null);
    renderRoutes('/system/accounts?page=2', 'platform.xlife.test');
    expect(await screen.findByText('平台管理 · 登录')).toBeInTheDocument();
    expect(screen.getByTestId('location')).toHaveTextContent(
      '/login?return_to=%2Fsystem%2Faccounts%3Fpage%3D2',
    );
    fireEvent.change(screen.getByLabelText('登录名'), {
      target: { value: 'root' },
    });
    fireEvent.change(screen.getByLabelText('密码'), {
      target: { value: 'test-login-password' },
    });
    fireEvent.click(screen.getByRole('button', { name: '登 录' }));
    expect(await screen.findByText('成员')).toBeInTheDocument();
    expect(screen.getByTestId('location')).toHaveTextContent(
      '/system/accounts?page=2',
    );
  });

  it.each([
    ['platform.xlife.test', '平台管理首页', '/api/platform/'],
    ['property.xlife.test', '物业工作台', '/api/property/'],
  ])(
    'keeps %s menus, shortcuts and requests in its scope',
    async (host, title, apiBase) => {
      const fetcher = mockApi();
      renderRoutes('/', host);
      expect(await screen.findByText(title)).toBeInTheDocument();
      for (const link of screen.getAllByRole('link')) {
        expect(link.getAttribute('href')).not.toMatch(
          /^\/(platform|property)(\/|$)/,
        );
      }
      fireEvent.click(screen.getAllByRole('link', { name: '个人资料' })[0]);
      expect(await screen.findByLabelText('显示名称')).toBeInTheDocument();
      expect(screen.getByTestId('location')).toHaveTextContent('/profile');
      expect(
        fetcher.mock.calls.every(([url]) =>
          new URL(String(url)).pathname.startsWith(apiBase),
        ),
      ).toBe(true);
    },
  );

  it('normalizes old return targets and company detail links', async () => {
    renderRoutes(
      '/login?return_to=' +
        encodeURIComponent(
          `/platform/property/companies/${companyId}?admins_page=2`,
        ),
      'platform.xlife.test',
    );
    expect(
      await screen.findByRole('link', { name: '返回公司列表' }),
    ).toHaveAttribute('href', '/companies');
    expect(screen.getByTestId('location')).toHaveTextContent(
      `/companies/${companyId}?admins_page=2`,
    );
    fireEvent.click(screen.getByRole('link', { name: '返回公司列表' }));
    expect(await screen.findByRole('link', { name: '详情' })).toHaveAttribute(
      'href',
      `/companies/${companyId}`,
    );
  });

  it('uses clean paths for the forced password flow', async () => {
    mockApi({ ...session, must_change_password: true, permissions: [] });
    renderRoutes('/profile', 'platform.xlife.test');
    expect(await screen.findByText('首次登录 · 修改密码')).toBeInTheDocument();
    expect(screen.getByTestId('location')).toHaveTextContent(
      '/change-password',
    );
  });

  it.each([
    ['platform.xlife.test', '/property/login', '/api/property/'],
    ['property.xlife.test', '/platform/login', '/api/platform/'],
    ['property.xlife.test', '/companies', '/api/platform/'],
    ['property.xlife.test', '/system/accounts', '/api/platform/'],
  ])('rejects client navigation to %s %s', async (host, path, foreignApi) => {
    const fetcher = mockApi();
    renderRoutes(path, host);
    await waitFor(() =>
      expect(screen.getByText('页面不存在')).toBeInTheDocument(),
    );
    expect(screen.getByTestId('location')).toHaveTextContent(path);
    expect(
      fetcher.mock.calls.every(
        ([url]) => !new URL(String(url)).pathname.startsWith(foreignApi),
      ),
    ).toBe(true);
  });
});
describe('admin navigation and identity', () => {
  it('shows both portal entry points and keeps each layout independent', async () => {
    renderRoutes('/');
    fireEvent.click(screen.getByRole('link', { name: '进入平台管理端' }));
    expect(await screen.findByText('平台管理首页')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('link', { name: '返回入口' }));
    fireEvent.click(screen.getByRole('link', { name: '进入物业管理端' }));
    expect(await screen.findByText('物业工作台')).toBeInTheDocument();
    expect(screen.queryByText('平台管理首页')).not.toBeInTheDocument();
  });
  it('returns to a protected deep link after login', async () => {
    const fetcher = mockApi(null);
    renderRoutes('/platform/system/accounts');
    expect(await screen.findByText('平台管理 · 登录')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('登录名'), {
      target: { value: 'root' },
    });
    fireEvent.change(screen.getByLabelText('密码'), {
      target: { value: 'test-login-password' },
    });
    fireEvent.click(screen.getByRole('button', { name: '登 录' }));
    expect(await screen.findByText('成员')).toBeInTheDocument();
    expect(
      fetcher.mock.calls.some(
        ([url, init]) =>
          String(url).endsWith('/admin-sessions') && init?.method === 'POST',
      ),
    ).toBe(true);
  });
  it('restricts the initial session to the password change page', async () => {
    const fetcher = mockApi({
      ...session,
      must_change_password: true,
      permissions: [],
    });
    renderRoutes('/platform/system/accounts');
    expect(await screen.findByText('首次登录 · 修改密码')).toBeInTheDocument();
    expect(screen.getByLabelText('当前密码')).toBeInTheDocument();
    expect(
      fetcher.mock.calls.every(
        ([url]) => !String(url).includes('/admin-accounts?'),
      ),
    ).toBe(true);
  });
  it('shows a retry state when identity restoration fails', async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockRejectedValueOnce(new TypeError('offline'))
      .mockResolvedValue(Response.json(session));
    vi.stubGlobal('fetch', fetcher);
    renderRoutes('/platform');
    expect(
      await screen.findByText('无法确认登录状态，请重试'),
    ).toBeInTheDocument();
    expect(screen.queryByText('平台管理首页')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '重 试' }));
    expect(await screen.findByText('平台管理首页')).toBeInTheDocument();
  });
  it('shows 403 without requesting a forbidden resource', async () => {
    const fetcher = mockApi({ ...session, permissions: ['admin.role.read'] });
    renderRoutes('/platform/system/accounts');
    expect(await screen.findByText('无权访问此页面')).toBeInTheDocument();
    expect(
      fetcher.mock.calls.some(([url]) =>
        String(url).includes('/admin-accounts?'),
      ),
    ).toBe(false);
  });
  it('hides write actions for a read-only account', async () => {
    mockApi({ ...session, permissions: ['admin.account.read'] });
    renderRoutes('/platform/system/accounts');
    expect(await screen.findByText('成员')).toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: '创建管理员' }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: '重置密码' }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '详情' })).toBeInTheDocument();
  });
  it('loads details on demand and sends CSRF for an account creation', async () => {
    const fetcher = mockApi();
    renderRoutes('/platform/system/accounts');
    await screen.findByText('成员');
    expect(
      fetcher.mock.calls.some(([url]) =>
        String(url).endsWith('/admin-accounts/member'),
      ),
    ).toBe(false);
    fireEvent.click(screen.getByRole('button', { name: '详情' }));
    await screen.findByText('管理员详情');
    await waitFor(() =>
      expect(
        fetcher.mock.calls.some(([url]) =>
          String(url).endsWith('/admin-accounts/member'),
        ),
      ).toBe(true),
    );
    fireEvent.click(screen.getByRole('button', { name: '关闭' }));
    await waitFor(() =>
      expect(screen.queryByText('管理员详情')).not.toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole('button', { name: '创建管理员' }));
    const drawer = within(await screen.findByRole('dialog'));
    fireEvent.change(drawer.getByLabelText('登录名'), {
      target: { value: 'new-user' },
    });
    fireEvent.change(drawer.getByLabelText('显示名称'), {
      target: { value: '新管理员' },
    });
    fireEvent.change(drawer.getByLabelText('初始密码'), {
      target: { value: 'test-new-password' },
    });
    fireEvent.change(drawer.getByLabelText('确认密码'), {
      target: { value: 'test-new-password' },
    });
    fireEvent.click(drawer.getByRole('button', { name: '保 存' }));
    await waitFor(() =>
      expect(
        fetcher.mock.calls.some(
          ([url, init]) =>
            String(url).endsWith('/admin-accounts') && init?.method === 'POST',
        ),
      ).toBe(true),
    );
    const call = fetcher.mock.calls.find(
      ([url, init]) =>
        String(url).endsWith('/admin-accounts') && init?.method === 'POST',
    )!;
    expect(new Headers(call[1]?.headers).get('X-CSRF-Token')).toBe(
      'csrf-token',
    );
    expect(JSON.parse(String(call[1]?.body))).toMatchObject({ role_ids: [] });
  });
  it.each(['/missing', '/platform/missing/deep', '/property/missing/deep'])(
    'shows 404 for %s',
    async (path) => {
      renderRoutes(path);
      await waitFor(() =>
        expect(screen.getByText('页面不存在')).toBeInTheDocument(),
      );
    },
  );
  it('guards company detail and only loads independently permitted sections', async () => {
    const fetcher = mockApi({
      ...session,
      permissions: ['property.company.read'],
    });
    renderRoutes(`/platform/property/companies/${companyId}`);
    expect((await screen.findAllByText('联系人')).length).toBeGreaterThan(0);
    expect(
      screen.queryByRole('button', { name: '开通公司管理员' }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: '创建小区' }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: '编辑' }),
    ).not.toBeInTheDocument();
    expect(
      fetcher.mock.calls.some(
        ([url]) =>
          String(url).includes('/communities?') ||
          String(url).includes(`/${companyId}/admin-accounts`),
      ),
    ).toBe(false);
  });
  it('does not load property data for a forbidden company detail route', async () => {
    const fetcher = mockApi({
      ...session,
      permissions: ['property.community.read'],
    });
    renderRoutes(`/platform/property/companies/${companyId}`);
    expect(await screen.findByText('无权访问此页面')).toBeInTheDocument();
    expect(
      fetcher.mock.calls.some(([url]) =>
        String(url).includes('/property-companies'),
      ),
    ).toBe(false);
  });
  it('treats an invalid dynamic company identifier as an unknown route', async () => {
    const fetcher = mockApi();
    renderRoutes('/platform/property/companies/not-a-uuid');
    await waitFor(() =>
      expect(screen.getByText('页面不存在')).toBeInTheDocument(),
    );
    expect(
      fetcher.mock.calls.some(([url]) =>
        String(url).includes('/property-companies'),
      ),
    ).toBe(false);
    expect(
      safeReturnTarget(
        'platform_admin',
        `/platform/property/companies/${companyId}?admins_page=2`,
      ),
    ).toBe(`/platform/property/companies/${companyId}?admins_page=2`);
    expect(
      safeReturnTarget(
        'platform_admin',
        '/platform/property/companies/not-a-uuid',
      ),
    ).toBe('/platform');
  });
  it('provisions a company administrator with CSRF and only the onboarding fields', async () => {
    const fetcher = mockApi();
    renderRoutes(`/platform/property/companies/${companyId}`);
    fireEvent.click(
      await screen.findByRole('button', { name: '开通公司管理员' }),
    );
    const drawer = within(await screen.findByRole('dialog'));
    fireEvent.change(drawer.getByLabelText('登录名'), {
      target: { value: 'new-company-admin' },
    });
    fireEvent.change(drawer.getByLabelText('显示名称'), {
      target: { value: '新公司管理员' },
    });
    fireEvent.change(drawer.getByLabelText('初始密码'), {
      target: { value: 'test-company-password' },
    });
    fireEvent.change(drawer.getByLabelText('确认密码'), {
      target: { value: 'test-company-password' },
    });
    fireEvent.click(drawer.getByRole('button', { name: '保 存' }));
    await waitFor(() =>
      expect(
        fetcher.mock.calls.some(
          ([url, init]) =>
            String(url).endsWith(`/${companyId}/admin-accounts`) &&
            init?.method === 'POST',
        ),
      ).toBe(true),
    );
    const call = fetcher.mock.calls.find(
      ([url, init]) =>
        String(url).endsWith(`/${companyId}/admin-accounts`) &&
        init?.method === 'POST',
    )!;
    expect(new Headers(call[1]?.headers).get('X-CSRF-Token')).toBe(
      'csrf-token',
    );
    expect(JSON.parse(String(call[1]?.body))).toEqual({
      login_name: 'new-company-admin',
      display_name: '新公司管理员',
      password: 'test-company-password',
    });
    await waitFor(() =>
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument(),
    );
    expect(
      fetcher.mock.calls.filter(
        ([url, init]) =>
          String(url).includes(`/${companyId}/admin-accounts?`) &&
          !init?.method,
      ).length,
    ).toBeGreaterThanOrEqual(2);
  });
  it('creates a community from company detail with the fixed company and refreshes its list', async () => {
    const fetcher = mockApi();
    renderRoutes(`/platform/property/companies/${companyId}`);
    fireEvent.click(await screen.findByRole('button', { name: '创建小区' }));
    const drawer = within(await screen.findByRole('dialog'));
    fireEvent.change(drawer.getByLabelText('小区编码'), {
      target: { value: 'NEW' },
    });
    fireEvent.change(drawer.getByLabelText('小区名称'), {
      target: { value: '新小区' },
    });
    fireEvent.change(drawer.getByLabelText('地址'), {
      target: { value: '新街道 1 号' },
    });
    fireEvent.click(drawer.getByRole('button', { name: '保 存' }));
    await waitFor(() =>
      expect(
        fetcher.mock.calls.some(
          ([url, init]) =>
            String(url).endsWith('/communities') && init?.method === 'POST',
        ),
      ).toBe(true),
    );
    const call = fetcher.mock.calls.find(
      ([url, init]) =>
        String(url).endsWith('/communities') && init?.method === 'POST',
    )!;
    expect(JSON.parse(String(call[1]?.body))).toEqual({
      property_company_id: companyId,
      code: 'NEW',
      name: '新小区',
      address: '新街道 1 号',
    });
    await waitFor(() =>
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument(),
    );
  });
  it('restores independent URL filters and pagination for company sections', async () => {
    const fetcher = mockApi();
    renderRoutes(
      `/platform/property/companies/${companyId}?communities_page=2&communities_page_size=10&communities_name=社区&admins_page=3&admins_login_name=manager`,
    );
    await screen.findByText('公司管理人员');
    const urls = fetcher.mock.calls.map(([url]) => new URL(String(url)));
    const communityQuery = urls.find((url) =>
      url.pathname.endsWith('/communities'),
    )!;
    const adminQuery = urls.find((url) =>
      url.pathname.endsWith(`/${companyId}/admin-accounts`),
    )!;
    expect(communityQuery.searchParams.get('page')).toBe('2');
    expect(communityQuery.searchParams.get('name')).toBe('社区');
    expect(communityQuery.searchParams.get('property_company_id')).toBe(
      companyId,
    );
    expect(adminQuery.searchParams.get('page')).toBe('3');
    expect(adminQuery.searchParams.get('login_name')).toBe('manager');
  });
  it.each([
    'https://evil.test/a',
    '//evil.test/a',
    '/property',
    '/platform/login',
    '/platform/change-password',
    '/platform/unknown',
    '/platform/../property',
  ])('rejects an unsafe return target: %s', (target) => {
    expect(safeReturnTarget('platform_admin', target)).toBe('/platform');
  });
});
