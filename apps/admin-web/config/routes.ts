import { adminApps } from '../src/app/admin-routes';

interface ConfiguredRoute {
  path: string;
  component: string;
  routes?: ConfiguredRoute[];
}

const routes: ConfiguredRoute[] = [
  { path: '/', component: '@/app/App' },
  ...[
    { app: adminApps.platform_admin, component: '@/app/platform/PlatformApp' },
    { app: adminApps.property_admin, component: '@/app/property/PropertyApp' },
  ].map(({ app, component }) => ({
    path: app.root,
    component,
    routes: [
      ...app.routes.map(({ path, component }) => ({ path, component })),
      { path: app.root + '/*', component: '@/components/NotFoundPage' },
    ],
  })),
  { path: '*', component: '@/components/NotFoundPage' },
];

export default routes;
