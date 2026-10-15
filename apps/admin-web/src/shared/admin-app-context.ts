import { createContext, useContext } from 'react';
import type { AdminScope, AuthStatus } from './admin-types';

export interface AdminRoute {
  path: string;
  sitePath?: string;
  component: string;
  title: string;
  menu?: string | true;
  menuParent?: string;
  permission?: string;
  states: AuthStatus[];
}

export interface AdminMenuGroup {
  id: string;
  title: string;
  path?: string;
}

export interface AdminAppContextValue {
  scope: AdminScope;
  title: string;
  theme: 'realDark' | 'light';
  homePath: string;
  loginPath: string;
  passwordPath: string;
  profilePath: string;
  menuGroups: AdminMenuGroup[];
  routes: AdminRoute[];
  path: (path: string) => string;
  findRoute: (pathname: string) => AdminRoute | undefined;
  returnTarget: (candidate: string | null) => string;
}

export const AdminAppContext = createContext<AdminAppContextValue | null>(null);

export function useAdminApp() {
  const context = useContext(AdminAppContext);
  if (!context)
    throw new Error('Admin navigation requires an application provider');
  return context;
}
