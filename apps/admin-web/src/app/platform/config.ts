import type { AdminAppConfig } from '../types';
import { platformRoutes } from './routes';

export const platformApp: AdminAppConfig = {
  scope: 'platform_admin',
  root: '/platform',
  hostname: process.env.UMI_APP_PLATFORM_HOST || 'platform.xlife.test',
  apiBase: process.env.UMI_APP_PLATFORM_API_BASE || '/api/platform',
  title: '平台管理',
  theme: 'realDark',
  menuGroups: [
    { id: 'payments', title: '支付与资金' },
    { id: 'property', title: '物业管理' },
    { id: 'system', title: '系统管理', path: '/platform/system' },
  ],
  routes: platformRoutes,
};
