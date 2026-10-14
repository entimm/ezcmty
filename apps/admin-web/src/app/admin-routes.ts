import type { AdminScope } from '../shared/admin-types';
import { platformApp } from './platform/config';
import { propertyApp } from './property/config';
import {
  currentHostname,
  pathForApp,
  returnTargetForApp,
  routesForApp,
} from './routing';

export const adminApps = {
  platform_admin: platformApp,
  property_admin: propertyApp,
};
export function scopeForHostname(hostname = currentHostname()) {
  return (Object.keys(adminApps) as AdminScope[]).find(
    (scope) =>
      adminApps[scope].hostname.toLowerCase() === hostname.toLowerCase(),
  );
}
export function adminPath(
  scope: AdminScope,
  path: string,
  hostname = currentHostname(),
) {
  return pathForApp(adminApps[scope], path, hostname);
}
export function routesForScope(
  scope: AdminScope,
  hostname = currentHostname(),
) {
  const selected = scopeForHostname(hostname);
  return selected && selected !== scope
    ? []
    : routesForApp(adminApps[scope], hostname);
}
export function safeReturnTarget(
  scope: AdminScope,
  candidate: string | null,
  hostname = currentHostname(),
) {
  return returnTargetForApp(adminApps[scope], candidate, hostname);
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
  const app = adminApps[scope];
  const entry = routes.find((route) => route.path === app.root);
  function convert(route: ScopedClientRoute) {
    if (route.path) route.path = pathForApp(app, route.path, hostname);
    if (route.children) {
      route.children.forEach(convert);
      route.routes = route.children;
    }
  }
  if (entry) convert(entry);
  routes.splice(0, routes.length, ...(entry ? [entry] : []));
}
