import { fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

import configuredRoutes from '../../../config/routes';
import { rootContainer } from '../../app';
import NotFoundPage from '../../components/NotFoundPage';
import LoginPage from '../../features/auth/LoginPage';
import ChangePasswordPage from '../../features/auth/ChangePasswordPage';
import ProfilePage from '../../features/profile/ProfilePage';
import WorkspaceCommunitiesPage from '../../features/property/CommunitiesPage';
import type { SessionResponse } from '../../shared/api/admin';
import { safeReturnTarget } from '../admin-routes';
import HomePage from '../../features/property/HomePage';
import PropertyApp from './PropertyApp';

const session: SessionResponse = {
  scope: 'property_admin',
  subject_id: '019a0000-0000-7000-8000-000000000001',
  login_name: 'company_admin',
  display_name: '物业管理员',
  permissions: ['property.company.read', 'property.community.read'],
  must_change_password: false,
  csrf_token: 'property-csrf',
};
const company = {
  id: '019a0000-0000-7000-8000-000000000002',
  code: 'COMPANY',
  name: '本公司',
  contact_name: '张先生',
  contact_phone: '13800000000',
  enabled: true,
  created_at: '2026-10-14T00:00:00Z',
  updated_at: '2026-10-14T00:00:00Z',
};
const community = {
  id: '019a0000-0000-7000-8000-000000000003',
  property_company_id: company.id,
  property_company_name: company.name,
  code: 'COMMUNITY',
  name: '本公司小区记录',
  address: '本公司小区地址',
  enabled: false,
  created_at: company.created_at,
  updated_at: company.updated_at,
};

function mockPropertyApi(initial: SessionResponse | null = session) {
  let identity = initial;
  const fetcher = vi.fn<typeof fetch>(async (url, init) => {
    const target = new URL(String(url), window.location.origin);
    const path = target.pathname;
    if (path === '/api/property/v1/admin-sessions') {
      identity = session;
      return Response.json(identity, { status: 201 });
    }
    if (!identity) return new Response(null, { status: 401 });
    if (path.endsWith('/admin-sessions/current')) {
      if (init?.method === 'DELETE') {
        identity = null;
        return new Response(null, { status: 204 });
      }
      return Response.json(identity);
    }
    if (path.endsWith('/password-changes')) {
      const data = JSON.parse(String(init?.body));
      if (data.current_password === 'wrong-password')
        return Response.json(
          {
            type: 'urn:problem:auth.invalid_old_password',
            instance: 'urn:request:property-password-error',
            request_id: 'property-password-error',
            code: 'auth.invalid_old_password',
            title: '当前密码不正确',
            detail: '当前密码不正确',
            status: 409,
          },
          {
            status: 409,
            headers: { 'Content-Type': 'application/problem+json' },
          },
        );
      identity = null;
      return new Response(null, { status: 204 });
    }
    if (path.endsWith('/admin-accounts/me')) {
      if (init?.method === 'PATCH') {
        const data = JSON.parse(String(init.body)) as { display_name: string };
        identity = { ...identity, display_name: data.display_name };
      }
      return Response.json({
        id: identity.subject_id,
        scope: identity.scope,
        login_name: identity.login_name,
        display_name: identity.display_name,
      });
    }
    if (path.endsWith('/property-companies/current'))
      return Response.json(company);
    if (path.endsWith('/communities'))
      return Response.json({
        items: [community],
        total: 7,
        page: Number(target.searchParams.get('page') || 1),
        page_size: Number(target.searchParams.get('page_size') || 20),
      });
    if (path.endsWith(`/communities/${community.id}`))
      return Response.json(community);
    throw new Error(`Unexpected request: ${path}`);
  });
  vi.stubGlobal('fetch', fetcher);
  return {
    fetcher,
    revoke: () => {
      identity = null;
    },
  };
}

const pages = {
  '@/features/property/HomePage': HomePage,
  '@/features/auth/LoginPage': LoginPage,
  '@/features/auth/ChangePasswordPage': ChangePasswordPage,
  '@/features/profile/ProfilePage': ProfilePage,
  '@/features/property/CommunitiesPage': WorkspaceCommunitiesPage,
  '@/components/NotFoundPage': NotFoundPage,
};

function renderProperty(path: string) {
  const routes = configuredRoutes.find(
    (route) => route.path === '/property',
  )!.routes!;
  return render(
    rootContainer(
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/property" element={<PropertyApp />}>
            {routes.map((route) => {
              const Page = pages[route.component as keyof typeof pages];
              return (
                <Route key={route.path} path={route.path} element={<Page />} />
              );
            })}
          </Route>
        </Routes>
      </MemoryRouter>,
    ),
  );
}

afterEach(() => vi.unstubAllGlobals());

describe('property login and workspace', () => {
  it('logs in to a protected deep link using only the property API', async () => {
    const { fetcher } = mockPropertyApi(null);
    renderProperty('/property/communities?name=本公司');
    expect(await screen.findByText('物业管理 · 登录')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('登录名'), {
      target: { value: 'company_admin' },
    });
    fireEvent.change(screen.getByLabelText('密码'), {
      target: { value: 'property-password' },
    });
    fireEvent.click(screen.getByRole('button', { name: '登 录' }));
    expect(await screen.findByText(community.name)).toBeInTheDocument();
    expect(
      fetcher.mock.calls.every(([url]) =>
        new URL(String(url), window.location.origin).pathname.startsWith(
          '/api/property/',
        ),
      ),
    ).toBe(true);
    expect(screen.queryByText('系统管理')).not.toBeInTheDocument();
    const login = fetcher.mock.calls.find(
      ([, init]) => init?.method === 'POST',
    )!;
    expect(JSON.parse(String(login[1]?.body))).toEqual({
      login_name: 'company_admin',
      password: 'property-password',
    });
    expect(
      safeReturnTarget('property_admin', '/platform/system/accounts'),
    ).toBe('/property');
  });

  it('limits the initial session to password change and requires a fresh login', async () => {
    const { fetcher } = mockPropertyApi({
      ...session,
      must_change_password: true,
      permissions: [],
    });
    renderProperty('/property');
    expect(await screen.findByText('首次登录 · 修改密码')).toBeInTheDocument();
    expect(
      fetcher.mock.calls.every(([url]) =>
        String(url).endsWith('/admin-sessions/current'),
      ),
    ).toBe(true);
    fireEvent.change(screen.getByLabelText('当前密码'), {
      target: { value: 'property-password' },
    });
    fireEvent.change(screen.getByLabelText('新密码'), {
      target: { value: 'new-property-password' },
    });
    fireEvent.change(screen.getByLabelText('确认密码'), {
      target: { value: 'new-property-password' },
    });
    fireEvent.click(screen.getByRole('button', { name: '保存新密码' }));
    expect(await screen.findByText('物业管理 · 登录')).toBeInTheDocument();
    const change = fetcher.mock.calls.find(([url]) =>
      String(url).endsWith('/password-changes'),
    )!;
    expect(new Headers(change[1]?.headers).get('X-CSRF-Token')).toBe(
      'property-csrf',
    );
    expect(screen.queryByText(company.name)).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('登录名'), {
      target: { value: 'company_admin' },
    });
    fireEvent.change(screen.getByLabelText('密码'), {
      target: { value: 'new-property-password' },
    });
    fireEvent.click(screen.getByRole('button', { name: '登 录' }));
    expect(await screen.findByText(company.name)).toBeInTheDocument();
    expect(screen.getByText(company.contact_phone)).toBeInTheDocument();
  });

  it('loads community details on demand and keeps company scope out of the form', async () => {
    const { fetcher } = mockPropertyApi();
    renderProperty(
      '/property/communities?page=2&page_size=5&name=本公司&enabled=false&property_company_id=outside',
    );
    expect(await screen.findByText(community.name)).toBeInTheDocument();
    expect(screen.queryByLabelText('物业公司')).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: '创建小区' }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: '编辑' }),
    ).not.toBeInTheDocument();
    const list = fetcher.mock.calls.find(([url]) =>
      String(url).includes('/communities?'),
    )!;
    const query = new URL(String(list[0]), window.location.origin).searchParams;
    expect(query.get('page')).toBe('2');
    expect(query.get('page_size')).toBe('5');
    expect(query.get('enabled')).toBe('false');
    expect(query.get('name')).toBe('本公司');
    expect(query.has('property_company_id')).toBe(false);
    expect(
      fetcher.mock.calls.some(([url]) =>
        String(url).endsWith(`/${community.id}`),
      ),
    ).toBe(false);
    fireEvent.click(screen.getByRole('button', { name: '查看详情' }));
    const detail = within(await screen.findByRole('dialog'));
    expect(await detail.findByText(company.name)).toBeInTheDocument();
    expect(detail.getByText('停用')).toBeInTheDocument();
    expect(
      detail.queryByRole('button', { name: '保 存' }),
    ).not.toBeInTheDocument();
  });

  it('clears community data and returns to property login after a revoked session', async () => {
    const { revoke } = mockPropertyApi();
    renderProperty('/property/communities');
    await screen.findByText(community.name);
    revoke();
    fireEvent.change(screen.getByLabelText('名称'), {
      target: { value: '重新查询' },
    });
    fireEvent.click(screen.getByRole('button', { name: '查 询' }));
    expect(await screen.findByText('物业管理 · 登录')).toBeInTheDocument();
    expect(screen.queryByText(community.name)).not.toBeInTheDocument();
    expect(screen.queryByText('本公司小区')).not.toBeInTheDocument();
  });

  it('shows 403 without loading communities when the permission is missing', async () => {
    const { fetcher } = mockPropertyApi({
      ...session,
      permissions: ['property.company.read'],
    });
    renderProperty('/property/communities');
    expect(await screen.findByText('无权访问此页面')).toBeInTheDocument();
    expect(
      fetcher.mock.calls.some(([url]) => String(url).includes('/communities')),
    ).toBe(false);
  });

  it('keeps personal account links available without requesting forbidden company data', async () => {
    const { fetcher } = mockPropertyApi({ ...session, permissions: [] });
    renderProperty('/property');
    expect(await screen.findByText('物业工作台')).toBeInTheDocument();
    expect(
      screen.getAllByRole('link', { name: '个人资料' }).length,
    ).toBeGreaterThan(0);
    expect(screen.queryByText('所属物业公司')).not.toBeInTheDocument();
    expect(screen.queryByText('小区查询')).not.toBeInTheDocument();
    expect(
      fetcher.mock.calls.some(([url]) =>
        String(url).includes('/property-companies'),
      ),
    ).toBe(false);
  });

  it('keeps the property session and password form after an incorrect old password', async () => {
    mockPropertyApi();
    renderProperty('/property/profile?tab=password');
    fireEvent.change(await screen.findByLabelText('当前密码'), {
      target: { value: 'wrong-password' },
    });
    fireEvent.change(screen.getByLabelText('新密码'), {
      target: { value: 'new-property-password' },
    });
    fireEvent.change(screen.getByLabelText('确认密码'), {
      target: { value: 'new-property-password' },
    });
    fireEvent.click(screen.getByRole('button', { name: '保存新密码' }));
    expect(await screen.findByText('当前密码不正确')).toBeInTheDocument();
    expect(screen.queryByText('物业管理 · 登录')).not.toBeInTheDocument();
    expect(screen.getByLabelText('新密码')).toHaveValue(
      'new-property-password',
    );
  });
});
