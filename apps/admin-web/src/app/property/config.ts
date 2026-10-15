import type { AdminAppConfig } from '../types';
import { propertyRoutes } from './routes';

export const propertyApp: AdminAppConfig = {
  scope: 'property_admin',
  root: '/property',
  hostname: process.env.UMI_APP_PROPERTY_HOST || 'property.xlife.test',
  apiBase: process.env.UMI_APP_PROPERTY_API_BASE || '/api/property',
  title: '物业管理',
  theme: 'light',
  menuGroups: [],
  routes: propertyRoutes,
};
