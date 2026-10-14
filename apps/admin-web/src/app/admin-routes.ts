import type { AdminScope, AuthStatus } from '../auth/session-context';

export interface AdminRoute {
  path: string;
  component: string;
  title: string;
  menu?: string;
  menuParent?: string;
  permission?: string;
  states: AuthStatus[];
}
export const adminRoots: Record<AdminScope, string> = {
  platform_admin: '/platform',
  property_admin: '/property',
};
export const adminTitles: Record<AdminScope, string> = {
  platform_admin: '平台管理',
  property_admin: '物业管理',
};
export const platformRoutes: AdminRoute[] = [
  {
    path: '/platform',
    component: '@/app/platform/HomePage',
    title: '首页',
    menu: '首页',
    states: ['authenticated'],
  },
  {
    path: '/platform/login',
    component: '@/features/admin/auth/LoginPage',
    title: '登录',
    states: ['anonymous'],
  },
  {
    path: '/platform/change-password',
    component: '@/features/admin/auth/ChangePasswordPage',
    title: '强制改密',
    states: ['password_change'],
  },
  {
    path: '/platform/profile',
    component: '@/features/admin/profile/ProfilePage',
    title: '个人中心',
    states: ['authenticated'],
  },
  {
    path: '/platform/property/companies',
    component: '@/features/admin/property/CompaniesPage',
    title: '物业公司',
    menu: '物业管理',
    permission: 'property.company.read',
    states: ['authenticated'],
  },
  {
    path: '/platform/property/companies/:company_id',
    component: '@/features/admin/property/CompanyDetailPage',
    title: '物业公司详情',
    menuParent: '/platform/property/companies',
    permission: 'property.company.read',
    states: ['authenticated'],
  },
  {
    path: '/platform/property/communities',
    component: '@/features/admin/property/CommunitiesPage',
    title: '小区管理',
    menu: '物业管理',
    permission: 'property.community.read',
    states: ['authenticated'],
  },
  {
    path: '/platform/system/accounts',
    component: '@/features/admin/accounts/AccountsPage',
    title: '管理员管理',
    menu: '系统管理',
    permission: 'admin.account.read',
    states: ['authenticated'],
  },
  {
    path: '/platform/system/roles',
    component: '@/features/admin/roles/RolesPage',
    title: '角色管理',
    menu: '系统管理',
    permission: 'admin.role.read',
    states: ['authenticated'],
  },
  {
    path: '/platform/system/audit-logs',
    component: '@/features/admin/audit/AuditPage',
    title: '审计日志',
    menu: '系统管理',
    permission: 'admin.audit.read',
    states: ['authenticated'],
  },
];
export function routesForScope(scope: AdminScope) {
  return scope === 'platform_admin' ? platformRoutes : [];
}
export function findAdminRoute(scope: AdminScope, pathname: string) {
  const identifier =
    /^[0-9a-f]{8}-[0-9a-f]{4}-[47][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
  const actual = pathname.split('/');
  return routesForScope(scope).find((route) => {
    const expected = route.path.split('/');
    return (
      expected.length === actual.length &&
      expected.every((part, i) =>
        part.startsWith(':') ? identifier.test(actual[i]) : part === actual[i],
      )
    );
  });
}
export function safeReturnTarget(scope: AdminScope, candidate: string | null) {
  const root = adminRoots[scope];
  if (
    !candidate ||
    !candidate.startsWith('/') ||
    candidate.startsWith('//') ||
    candidate.includes('\\')
  )
    return root;
  try {
    const target = new URL(candidate, 'https://admin.invalid');
    if (target.origin !== 'https://admin.invalid' || target.hash) return root;
    const route = findAdminRoute(scope, target.pathname);
    return route?.states.includes('authenticated')
      ? `${target.pathname}${target.search}`
      : root;
  } catch {
    return root;
  }
}
