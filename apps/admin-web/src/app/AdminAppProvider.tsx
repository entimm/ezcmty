import { useMemo, type ReactNode } from 'react';
import { AdminScopeProvider } from '../auth/AdminScopeProvider';
import { AdminAppContext } from '../shared/admin-app-context';
import {
  currentHostname,
  findRouteForApp,
  pathForApp,
  returnTargetForApp,
  routesForApp,
} from './routing';
import type { AdminAppConfig } from './types';

export function AdminAppProvider({
  app,
  children,
}: {
  app: AdminAppConfig;
  children: ReactNode;
}) {
  const hostname = currentHostname();
  const value = useMemo(() => {
    const path = (value: string) => pathForApp(app, value, hostname);
    return {
      scope: app.scope,
      title: app.title,
      theme: app.theme,
      homePath: path(app.root),
      loginPath: path(app.root + '/login'),
      passwordPath: path(app.root + '/change-password'),
      profilePath: path(app.root + '/profile'),
      menuGroups: app.menuGroups.map((group) => ({
        ...group,
        path: group.path ? path(group.path) : undefined,
      })),
      routes: routesForApp(app, hostname),
      path,
      findRoute: (pathname: string) => findRouteForApp(app, pathname, hostname),
      returnTarget: (candidate: string | null) =>
        returnTargetForApp(app, candidate, hostname),
    };
  }, [app, hostname]);
  return (
    <AdminAppContext.Provider value={value}>
      <AdminScopeProvider
        scope={app.scope}
        apiBase={app.apiBase}
        authenticationEnabled
      >
        {children}
      </AdminScopeProvider>
    </AdminAppContext.Provider>
  );
}
