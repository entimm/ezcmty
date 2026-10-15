import { render } from '@testing-library/react';

import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';

import type { ReactElement } from 'react';

import { vi } from 'vitest';

import App from '@/app/App';

import configuredRoutes from '../../config/routes';

import { patchClientRoutes, rootContainer } from '@/app';

import PlatformApp from '@/app/platform/PlatformApp';

import PlatformHome from '@/features/platform/HomePage';

import PropertyApp from '@/app/property/PropertyApp';

import PropertyHome from '@/features/property/HomePage';

import NotFoundPage from '@/components/NotFoundPage';

import LoginPage from '@/features/auth/LoginPage';

import ChangePasswordPage from '@/features/auth/ChangePasswordPage';

import ProfilePage from '@/features/profile/ProfilePage';

import AccountsPage from '@/features/platform/accounts/AccountsPage';

import RolesPage from '@/features/platform/roles/RolesPage';

import AuditPage from '@/features/platform/audit/AuditPage';

import CompaniesPage from '@/features/platform/property/CompaniesPage';

import CompanyDetailPage from '@/features/platform/property/CompanyDetailPage';

import CommunitiesPage from '@/features/platform/property/CommunitiesPage';

import WorkspaceCommunitiesPage from '@/features/property/CommunitiesPage';
import HousesPage from '@/features/property/housing/HousesPage';
import HouseDetailPage from '@/features/property/housing/HouseDetailPage';

import type { SessionResponse } from '@/shared/api/admin';

const pages = {
  '@/app/App': App,
  '@/app/platform/PlatformApp': PlatformApp,
  '@/features/platform/HomePage': PlatformHome,
  '@/app/property/PropertyApp': PropertyApp,
  '@/features/property/HomePage': PropertyHome,
  '@/components/NotFoundPage': NotFoundPage,
  '@/features/auth/LoginPage': LoginPage,
  '@/features/auth/ChangePasswordPage': ChangePasswordPage,
  '@/features/profile/ProfilePage': ProfilePage,
  '@/features/platform/accounts/AccountsPage': AccountsPage,
  '@/features/platform/roles/RolesPage': RolesPage,
  '@/features/platform/audit/AuditPage': AuditPage,
  '@/features/platform/property/CompaniesPage': CompaniesPage,
  '@/features/platform/property/CompanyDetailPage': CompanyDetailPage,
  '@/features/platform/property/CommunitiesPage': CommunitiesPage,
  '@/features/property/CommunitiesPage': WorkspaceCommunitiesPage,
  '@/features/property/housing/HousesPage': HousesPage,
  '@/features/property/housing/HouseDetailPage': HouseDetailPage,
};

export const session: SessionResponse = {
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

export const companyId = '019a0000-0000-7000-8000-000000000001';

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

export function mockApi(
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

export function renderRoutes(path: string, hostname?: string) {
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
