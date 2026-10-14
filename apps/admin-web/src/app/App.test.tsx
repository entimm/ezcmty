import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import type { ReactElement } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import App from './App';
import configuredRoutes from '../../config/routes';
import { rootContainer } from '../app';
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
function mockApi(identity: SessionResponse | null = session) {
  const fetcher = vi.fn<typeof fetch>(async (url, init) => {
    const path = new URL(String(url), window.location.origin).pathname;
    if (path.endsWith('/admin-sessions/current'))
      return identity
        ? Response.json(identity)
        : new Response(null, { status: 401 });
    if (path.endsWith('/admin-sessions') && init?.method === 'POST')
      return Response.json(session, { status: 201 });
    if (path.endsWith('/admin-accounts/me'))
      return Response.json({
        id: 'root',
        scope: 'platform_admin',
        login_name: 'root',
        display_name: '测试管理员',
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
}
function routeElements(routes: ConfiguredRoute[]): ReactElement[] {
  return routes.map((route) => {
    const Page = pages[route.component as keyof typeof pages];
    return (
      <Route key={route.path} path={route.path} element={<Page />}>
        {route.routes && routeElements(route.routes)}
      </Route>
    );
  });
}
function renderRoutes(path: string) {
  return render(
    rootContainer(
      <MemoryRouter initialEntries={[path]}>
        <Routes>{routeElements(configuredRoutes)}</Routes>
      </MemoryRouter>,
    ),
  );
}
describe('admin navigation and identity', () => {
  it('shows both portal entry points and keeps each layout independent', async () => {
    renderRoutes('/');
    fireEvent.click(screen.getByRole('link', { name: '进入平台管理端' }));
    expect(await screen.findByText('平台管理首页')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('link', { name: '返回入口' }));
    fireEvent.click(screen.getByRole('link', { name: '进入物业管理端' }));
    expect(await screen.findByText('物业管理首页')).toBeInTheDocument();
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
