export default [
  { path: '/', component: '@/app/App' },
  {
    path: '/platform',
    component: '@/app/platform/PlatformApp',
    routes: [
      { path: '/platform', component: '@/app/platform/HomePage' },
      { path: '/platform/*', component: '@/components/NotFoundPage' },
    ],
  },
  {
    path: '/property',
    component: '@/app/property/PropertyApp',
    routes: [
      { path: '/property', component: '@/app/property/HomePage' },
      { path: '/property/*', component: '@/components/NotFoundPage' },
    ],
  },
  { path: '*', component: '@/components/NotFoundPage' },
];
