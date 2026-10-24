import type { Scope } from '../shared/types';
export interface Route {
  page: string;
  path: string;
  title: string;
  permission?: string;
  parent?: string;
  companyScope?: boolean;
}
const shared: Route[] = [
  { page: 'home', path: '/', title: '工作台', companyScope: true },
  { page: 'login', path: '/login', title: '登录' },
  { page: 'change-password', path: '/change-password', title: '强制改密' },
  { page: 'profile', path: '/profile', title: '个人中心', companyScope: true },
];
export const routes: Record<Scope, Route[]> = {
  platform: [
    ...shared,
    {
      page: 'companies',
      path: '/companies',
      title: '物业公司',
      permission: 'property.company.read',
    },
    {
      page: 'company-detail',
      path: '/companies/:company',
      title: '物业公司详情',
      parent: 'companies',
      permission: 'property.company.read',
    },
    {
      page: 'platform-communities',
      path: '/communities',
      title: '小区管理',
      permission: 'property.community.read',
    },
    {
      page: 'accounts',
      path: '/system/accounts',
      title: '管理员',
      permission: 'admin.account.read',
    },
    {
      page: 'roles',
      path: '/system/roles',
      title: '角色与权限',
      permission: 'admin.role.read',
    },
    {
      page: 'audit',
      path: '/system/audit-logs',
      title: '审计日志',
      permission: 'admin.audit.read',
    },
    {
      page: 'payments',
      path: '/payments',
      title: '支付记录',
      permission: 'platform.payment.read',
    },
    {
      page: 'payment-detail',
      path: '/payments/:payment_id',
      title: '支付与资金详情',
      parent: 'payments',
      permission: 'platform.payment.read',
    },
    {
      page: 'reconciliation',
      path: '/payment-reconciliation',
      title: '资金核对',
      permission: 'platform.payment_reconciliation.read',
    },
    {
      page: 'payment-configuration',
      path: '/companies/:company/payment-configuration',
      title: '收款配置',
      parent: 'companies',
      permission: 'platform.payment_config.read',
    },
    ...importRoutes('platform'),
  ],
  property: [
    ...shared,
    {
      page: 'company',
      path: '/company',
      title: '公司资料',
      permission: 'property.company.read',
      companyScope: true,
    },
    {
      page: 'communities',
      path: '/communities',
      title: '小区资料',
      permission: 'property.community.read',
      companyScope: true,
    },
    {
      page: 'houses',
      path: '/houses',
      title: '房屋管理',
      permission: 'property.house.read',
    },
    {
      page: 'houses',
      path: '/communities/:community_id/houses',
      title: '房屋管理',
      permission: 'property.house.read',
    },
    {
      page: 'house-detail',
      path: '/communities/:community_id/houses/:house_id',
      title: '房屋详情',
      parent: 'houses',
      permission: 'property.house.read',
    },
    {
      page: 'bills',
      path: '/bills',
      title: '物业费账单',
      permission: 'property.bill.read',
    },
    {
      page: 'bills',
      path: '/communities/:community_id/bills',
      title: '物业费账单',
      permission: 'property.bill.read',
    },
    {
      page: 'bill-detail',
      path: '/communities/:community_id/bills/:bill_id',
      title: '账单详情',
      parent: 'bills',
      permission: 'property.bill.read',
    },
    {
      page: 'claims',
      path: '/house-claims',
      title: '房屋认领审核',
      permission: 'property.house_claim.read',
    },
    {
      page: 'claim-detail',
      path: '/house-claims/:claim_id',
      title: '认领申请详情',
      parent: 'claims',
      permission: 'property.house_claim.read',
    },
    {
      page: 'bindings',
      path: '/resident-house-bindings',
      title: '居民房屋绑定',
      permission: 'property.resident_house_binding.read',
    },
    {
      page: 'binding-detail',
      path: '/resident-house-bindings/:binding_id',
      title: '居民房屋绑定详情',
      parent: 'bindings',
      permission: 'property.resident_house_binding.read',
    },
    {
      page: 'payments',
      path: '/payments',
      title: '线上收款',
      permission: 'property.payment.read',
    },
    {
      page: 'payment-detail',
      path: '/payments/:payment_id',
      title: '支付与资金结果',
      parent: 'payments',
      permission: 'property.payment.read',
    },
    {
      page: 'reconciliation',
      path: '/payment-reconciliation',
      title: '核对结果',
      permission: 'property.payment_reconciliation.read',
      companyScope: true,
    },
    {
      page: 'payment-configuration',
      path: '/payment-configuration',
      title: '收款信息',
      permission: 'property.payment_config.read',
      companyScope: true,
    },
    ...importRoutes('property'),
  ],
};
function importRoutes(scope: Scope): Route[] {
  return [
    {
      page: 'imports',
      path: '/imports',
      title: scope === 'platform' ? '导入历史' : '导入中心',
      permission: `${scope}.import.read`,
    },
    {
      page: 'import-new',
      path: '/imports/new',
      title: '新建导入',
      permission: `${scope}.import.create`,
      parent: 'imports',
    },
    {
      page: 'import-detail',
      path: '/imports/:batch_id',
      title: '导入批次详情',
      permission: `${scope}.import.read`,
      parent: 'imports',
    },
  ];
}
export const configuredHosts = {
  platform: process.env.UMI_APP_PLATFORM_HOST || 'platform.xlife.test',
  property: process.env.UMI_APP_PROPERTY_HOST || 'property.xlife.test',
};
export function resolveScope(
  hostname: string,
  pathname: string,
): Scope | 'portal' | null {
  const host = hostname.toLowerCase();
  for (const scope of ['platform', 'property'] as const)
    if (configuredHosts[scope].toLowerCase() === host) return scope;
  if (!['localhost', '127.0.0.1', '[::1]'].includes(host)) return null;
  if (pathname === '/') return 'portal';
  return pathname === '/platform' || pathname.startsWith('/platform/')
    ? 'platform'
    : pathname === '/property' || pathname.startsWith('/property/')
      ? 'property'
      : null;
}
export function appPrefix(scope: Scope, hostname = window.location.hostname) {
  return configuredHosts[scope].toLowerCase() === hostname.toLowerCase()
    ? ''
    : `/${scope}`;
}
export function matchRoute(
  scope: Scope,
  pathname: string,
  hostname = window.location.hostname,
): { route: Route; params: Record<string, string> } | null {
  let path = pathname;
  const prefix = appPrefix(scope, hostname);
  let legacyPlatformGroup = false;
  if (prefix) {
    if (path !== prefix && !path.startsWith(prefix + '/')) return null;
    path = path.slice(prefix.length) || '/';
    legacyPlatformGroup = scope === 'platform';
  } else if (path.startsWith(`/${scope}/`)) {
    path = path.slice(scope.length + 1);
    legacyPlatformGroup = scope === 'platform';
  }
  if (legacyPlatformGroup && path.startsWith('/property/'))
    path = path.slice('/property'.length);
  for (const route of [...routes[scope]].sort(
    (a, b) => b.path.split('/').length - a.path.split('/').length,
  )) {
    const actual = path.split('/'),
      expected = route.path.split('/');
    if (actual.length !== expected.length) continue;
    const params: Record<string, string> = {};
    let matched = true;
    for (let i = 0; i < expected.length; i++) {
      if (expected[i].startsWith(':')) {
        let value: string;
        try {
          value = decodeURIComponent(actual[i]);
        } catch {
          matched = false;
          break;
        }
        if (
          !/^[0-9a-f]{8}-[0-9a-f]{4}-[47][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(
            value,
          )
        ) {
          matched = false;
          break;
        }
        params[expected[i].slice(1)] = value;
      } else if (actual[i] !== expected[i]) {
        matched = false;
        break;
      }
    }
    if (matched) return { route, params };
  }
  return null;
}
export function routePath(
  scope: Scope,
  page: string,
  params: Record<string, string | undefined> = {},
  hostname = window.location.hostname,
) {
  const normalized: Record<string, string | undefined> = {
    ...params,
    ...(page === 'payment-detail'
      ? { payment_id: params.payment_id || params.id }
      : {}),
    ...(page === 'import-detail'
      ? { batch_id: params.batch_id || params.id }
      : {}),
    company: params.company || params.company_id,
  };
  const options = routes[scope]
    .filter((route) => route.page === page)
    .sort((a, b) => b.path.length - a.path.length);
  const target =
    options.find((route) =>
      [...route.path.matchAll(/:([a-z_]+)/g)].every(
        ([, key]) => normalized[key as keyof typeof normalized],
      ),
    ) || options[0];
  if (!target) throw new Error('未注册的后台页面');
  const used = new Set<string>();
  const path = target.path.replace(/:([a-z_]+)/g, (_, key: string) => {
    used.add(key);
    const value = normalized[key as keyof typeof normalized];
    if (!value) throw new Error('缺少页面资源标识');
    return encodeURIComponent(value);
  });
  const query = new URLSearchParams();
  Object.entries(normalized).forEach(([key, value]) => {
    if (
      value !== undefined &&
      !used.has(key) &&
      key !== 'company_id' &&
      !(key === 'id' && (used.has('payment_id') || used.has('batch_id')))
    )
      query.set(key, value);
  });
  return (
    (appPrefix(scope, hostname) + path).replace(/\/$/, '') +
      (query.size ? `?${query}` : '') || '/'
  );
}
export function safeReturn(
  scope: Scope,
  candidate: string | null,
  hostname = window.location.hostname,
) {
  const home = routePath(scope, 'home', {}, hostname);
  if (
    !candidate ||
    !candidate.startsWith('/') ||
    candidate.startsWith('//') ||
    candidate.includes('\\')
  )
    return home;
  try {
    const url = new URL(candidate, 'https://admin.invalid');
    if (url.origin !== 'https://admin.invalid' || url.hash) return home;
    const match = matchRoute(scope, url.pathname, hostname);
    return match && !['login', 'change-password'].includes(match.route.page)
      ? url.pathname + url.search
      : home;
  } catch {
    return home;
  }
}
