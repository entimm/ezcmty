import type { AdminRoute } from '../shared/admin-app-context';
import type { AdminAppConfig } from './types';

export function currentHostname() {
  return typeof window === 'undefined' ? '' : window.location.hostname;
}

function routeParameters(
  template: string,
  pathname: string,
  identifiers = false,
) {
  const expected = template.split('/'),
    actual = pathname.split('/');
  if (expected.length !== actual.length) return;
  const uuid =
    /^[0-9a-f]{8}-[0-9a-f]{4}-[47][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
  const parameters: Record<string, string> = {};
  for (let i = 0; i < expected.length; i++) {
    if (expected[i].startsWith(':')) {
      if (!actual[i] || (identifiers && !uuid.test(actual[i]))) return;
      parameters[expected[i].slice(1)] = actual[i];
    } else if (expected[i] !== actual[i]) return;
  }
  return parameters;
}

export function pathForApp(
  app: AdminAppConfig,
  path: string,
  hostname = currentHostname(),
) {
  if (app.hostname.toLowerCase() !== hostname.toLowerCase()) return path;
  const separator = path.search(/[?#]/);
  const pathname = separator === -1 ? path : path.slice(0, separator);
  const suffix = separator === -1 ? '' : path.slice(separator);
  for (const route of app.routes) {
    if (!route.sitePath) continue;
    const parameters = routeParameters(route.path, pathname);
    if (parameters)
      return (
        route.sitePath.replace(
          /:([^/]+)/g,
          (_, name: string) => parameters[name],
        ) + suffix
      );
  }
  if (pathname === app.root) return '/' + suffix;
  return pathname.startsWith(app.root + '/')
    ? pathname.slice(app.root.length) + suffix
    : path;
}

export function routesForApp(
  app: AdminAppConfig,
  hostname = currentHostname(),
): AdminRoute[] {
  return app.routes.map((route) => ({
    ...route,
    path: pathForApp(app, route.path, hostname),
    menuParent: route.menuParent
      ? pathForApp(app, route.menuParent, hostname)
      : undefined,
  }));
}

export function findRouteForApp(
  app: AdminAppConfig,
  pathname: string,
  hostname = currentHostname(),
) {
  return routesForApp(app, hostname).find((route) =>
    routeParameters(route.path, pathname, true),
  );
}

export function returnTargetForApp(
  app: AdminAppConfig,
  candidate: string | null,
  hostname = currentHostname(),
) {
  const root = pathForApp(app, app.root, hostname);
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
    const pathname = pathForApp(app, target.pathname, hostname);
    return findRouteForApp(app, pathname, hostname)?.states.includes(
      'authenticated',
    )
      ? pathname + target.search
      : root;
  } catch {
    return root;
  }
}
