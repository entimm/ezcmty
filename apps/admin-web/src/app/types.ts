import type { AdminMenuGroup, AdminRoute } from '../shared/admin-app-context';
import type { AdminScope } from '../shared/admin-types';

export interface AdminAppConfig {
  scope: AdminScope;
  root: string;
  hostname: string;
  apiBase: string;
  title: string;
  theme: 'realDark' | 'light';
  menuGroups: AdminMenuGroup[];
  routes: AdminRoute[];
}
