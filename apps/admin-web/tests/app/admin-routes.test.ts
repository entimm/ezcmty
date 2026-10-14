import { matchRoutes } from 'react-router-dom';
import { describe, expect, it } from 'vitest';

import configuredRoutes from '../../config/routes';
import {
  adminPath,
  patchAdminClientRoutes,
  routesForScope,
  safeReturnTarget,
  scopeForHostname,
} from '@/app/admin-routes';

interface ConfiguredRoute {
  path: string;
  component: string;
  routes?: ConfiguredRoute[];
}
interface ClientRoute {
  path: string;
  element: string;
  children?: ClientRoute[];
}
function clientRoutes(
  routes: ConfiguredRoute[] = configuredRoutes,
): ClientRoute[] {
  return routes.map(({ path, component, routes: children }) => ({
    path,
    element: component,
    children: children && clientRoutes(children),
  }));
}
const companyId = '11111111-1111-4111-8111-111111111111';

describe('domain routes', () => {
  it.each([
    ['platform.xlife.test', 'platform_admin', '@/features/platform/HomePage'],
    ['property.xlife.test', 'property_admin', '@/features/property/HomePage'],
  ] as const)(
    'selects only the %s application at the root',
    (host, scope, page) => {
      const routes = clientRoutes();
      patchAdminClientRoutes(routes, host);
      expect(matchRoutes(routes, '/')?.at(-1)?.route.element).toBe(page);
      expect(matchRoutes(routes, '/login')?.at(-1)?.route.element).toBe(
        '@/features/auth/LoginPage',
      );
      expect(routesForScope(scope, host).map((route) => route.path)).toContain(
        '/profile',
      );
      const peer =
        scope === 'platform_admin' ? 'property_admin' : 'platform_admin';
      expect(routesForScope(peer, host)).toEqual([]);
      for (const path of ['/platform', '/property/login', '/missing']) {
        expect(matchRoutes(routes, path)?.at(-1)?.route.element).toBe(
          '@/components/NotFoundPage',
        );
      }
    },
  );

  it('selects distinct community pages and rejects platform pages on the property host', () => {
    const platform = clientRoutes(),
      property = clientRoutes();
    patchAdminClientRoutes(platform, 'platform.xlife.test');
    patchAdminClientRoutes(property, 'property.xlife.test');
    expect(matchRoutes(platform, '/communities')?.at(-1)?.route.element).toBe(
      '@/features/platform/property/CommunitiesPage',
    );
    expect(matchRoutes(property, '/communities')?.at(-1)?.route.element).toBe(
      '@/features/property/CommunitiesPage',
    );
    expect(
      matchRoutes(platform, `/companies/${companyId}`)?.at(-1)?.route.element,
    ).toBe('@/features/platform/property/CompanyDetailPage');
    for (const path of ['/companies', '/system/accounts']) {
      expect(matchRoutes(property, path)?.at(-1)?.route.element).toBe(
        '@/components/NotFoundPage',
      );
    }
  });

  it('keeps direct development routes and matches hostnames exactly', () => {
    const routes = clientRoutes(),
      before = structuredClone(routes);
    patchAdminClientRoutes(routes, 'localhost');
    expect(routes).toEqual(before);
    expect(adminPath('platform_admin', '/platform/profile', 'localhost')).toBe(
      '/platform/profile',
    );
    expect(scopeForHostname('PLATFORM.XLIFE.TEST')).toBe('platform_admin');
    expect(scopeForHostname('platform.xlife.test.example.org')).toBeUndefined();
    expect(scopeForHostname('other.xlife.test')).toBeUndefined();
  });
});

describe('domain login return targets', () => {
  it('normalizes valid clean and legacy targets while preserving filters', () => {
    for (const path of [
      `/companies/${companyId}?admins_page=2`,
      `/platform/property/companies/${companyId}?admins_page=2`,
    ]) {
      expect(
        safeReturnTarget('platform_admin', path, 'platform.xlife.test'),
      ).toBe(`/companies/${companyId}?admins_page=2`);
    }
    expect(
      safeReturnTarget('platform_admin', '/platform', 'platform.xlife.test'),
    ).toBe('/');
    expect(
      safeReturnTarget(
        'property_admin',
        '/property/communities?page=2',
        'property.xlife.test',
      ),
    ).toBe('/communities?page=2');
  });

  it.each([
    null,
    'https://example.org/',
    '//example.org/',
    '/\\example.org/',
    '/login',
    '/change-password',
    '/platform/login',
    '/platform/change-password',
    '/property/profile',
    '/companies/not-a-uuid',
    '/profile#password',
    '/platform/../property/profile',
    '/platform/property/profile',
    '/missing',
  ])('rejects unsafe, foreign, unknown or looping target %s', (candidate) => {
    expect(
      safeReturnTarget('platform_admin', candidate, 'platform.xlife.test'),
    ).toBe('/');
  });

  it('rejects platform routes on the property host', () => {
    for (const path of [
      '/companies',
      '/system/accounts',
      '/platform/profile',
    ]) {
      expect(
        safeReturnTarget('property_admin', path, 'property.xlife.test'),
      ).toBe('/');
    }
  });
});
