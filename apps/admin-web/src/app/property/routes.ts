import type { AdminRoute } from '../../shared/admin-app-context';

export const propertyRoutes: AdminRoute[] = [
  {
    path: '/property',
    component: '@/features/property/HomePage',
    title: '工作台',
    menu: 'home',
    states: ['authenticated'],
  },
  {
    path: '/property/login',
    component: '@/features/auth/LoginPage',
    title: '登录',
    states: ['anonymous'],
  },
  {
    path: '/property/change-password',
    component: '@/features/auth/ChangePasswordPage',
    title: '强制改密',
    states: ['password_change'],
  },
  {
    path: '/property/profile',
    component: '@/features/profile/ProfilePage',
    title: '个人中心',
    states: ['authenticated'],
  },
  {
    path: '/property/communities',
    component: '@/features/property/CommunitiesPage',
    title: '小区查询',
    menu: 'property',
    permission: 'property.community.read',
    states: ['authenticated'],
  },
];
