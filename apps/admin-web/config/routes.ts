import { platformRoutes, propertyRoutes } from '../src/app/admin-routes';

export default [
  { path: '/', component: '@/app/App' },
  {
    path: '/platform',
    component: '@/app/platform/PlatformApp',
    routes: [
      ...platformRoutes.map(({ path, component }) => ({ path, component })),
      { path: '/platform/*', component: '@/components/NotFoundPage' },
    ],
  },
  {
    path: '/property',
    component: '@/app/property/PropertyApp',
    routes: [
      ...propertyRoutes.map(({ path, component }) => ({ path, component })),
      { path: '/property/*', component: '@/components/NotFoundPage' },
    ],
  },
  { path: '*', component: '@/components/NotFoundPage' },
];
