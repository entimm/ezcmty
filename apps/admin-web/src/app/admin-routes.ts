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
const adminHosts: Record<AdminScope, string> = {
  platform_admin: process.env.UMI_APP_PLATFORM_HOST || 'platform.xlife.test',
  property_admin: process.env.UMI_APP_PROPERTY_HOST || 'property.xlife.test',
};

function currentHostname() {
  return typeof window === 'undefined' ? '' : window.location.hostname;
}

export function scopeForHostname(hostname = currentHostname()) {
  return (Object.keys(adminHosts) as AdminScope[]).find(
    (scope) => adminHosts[scope].toLowerCase() === hostname.toLowerCase(),
  );
}

// Build configuration keeps the prefixed routes; domain sites use root paths.
export function adminPath(
  scope: AdminScope,
  path: string,
  hostname = currentHostname(),
) {
  if (scopeForHostname(hostname) !== scope) return path;
  const prefix =
    scope === 'platform_admin' &&
    /^\/platform\/property\/(companies|communities)(\/|\?|$)/.test(path)
      ? '/platform/property'
      : adminRoots[scope];
  if (path === prefix) return '/';
  return path.startsWith(`${prefix}/`) ? path.slice(prefix.length) : path;
}

export function adminRoot(scope: AdminScope, hostname = currentHostname()) {
  return adminPath(scope, adminRoots[scope], hostname);
}

export interface ScopedClientRoute {
  path?: string;
  children?: ScopedClientRoute[];
  routes?: ScopedClientRoute[];
}

export function patchAdminClientRoutes(
  routes: ScopedClientRoute[],
  hostname = currentHostname(),
) {
  const scope = scopeForHostname(hostname);
  if (!scope) return;
  const entry = routes.find((route) => route.path === adminRoots[scope]);
  function convert(route: ScopedClientRoute) {
    if (route.path) route.path = adminPath(scope!, route.path, hostname);
    if (route.children) {
      route.children.forEach(convert);
      // Umi also exposes children as routes for layout consumers.
      route.routes = route.children;
    }
  }
  if (entry) convert(entry);
  routes.splice(0, routes.length, ...(entry ? [entry] : []));
}
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
export const propertyRoutes: AdminRoute[] = [
  {
    path: '/property',
    component: '@/app/property/HomePage',
    title: '工作台',
    menu: '首页',
    states: ['authenticated'],
  },
  {
    path: '/property/login',
    component: '@/features/admin/auth/LoginPage',
    title: '登录',
    states: ['anonymous'],
  },
  {
    path: '/property/change-password',
    component: '@/features/admin/auth/ChangePasswordPage',
    title: '强制改密',
    states: ['password_change'],
  },
  {
    path: '/property/profile',
    component: '@/features/admin/profile/ProfilePage',
    title: '个人中心',
    states: ['authenticated'],
  },
  {
    path: '/property/communities',
    component: '@/features/admin/property/WorkspaceCommunitiesPage',
    title: '小区查询',
    menu: '物业管理',
    permission: 'property.community.read',
    states: ['authenticated'],
  },
];
export function routesForScope(
  scope: AdminScope,
  hostname = currentHostname(),
) {
  const selected = scopeForHostname(hostname);
  if (selected && selected !== scope) return [];
  const routes = scope === 'platform_admin' ? platformRoutes : propertyRoutes;
  if (!selected) return routes;
  return routes.map((route) => ({
    ...route,
    path: adminPath(scope, route.path, hostname),
    menuParent: route.menuParent
      ? adminPath(scope, route.menuParent, hostname)
      : undefined,
  }));
}
export function findAdminRoute(
  scope: AdminScope,
  pathname: string,
  hostname = currentHostname(),
) {
  const identifier =
    /^[0-9a-f]{8}-[0-9a-f]{4}-[47][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
  const actual = pathname.split('/');
  return routesForScope(scope, hostname).find((route) => {
    const expected = route.path.split('/');
    return (
      expected.length === actual.length &&
      expected.every((part, i) =>
        part.startsWith(':') ? identifier.test(actual[i]) : part === actual[i],
      )
    );
  });
}
export function safeReturnTarget(
  scope: AdminScope,
  candidate: string | null,
  hostname = currentHostname(),
) {
  const root = adminRoot(scope, hostname);
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
    const pathname = adminPath(scope, target.pathname, hostname);
    const route = findAdminRoute(scope, pathname, hostname);
    return route?.states.includes('authenticated')
      ? `${pathname}${target.search}`
      : root;
  } catch {
    return root;
  }
}
