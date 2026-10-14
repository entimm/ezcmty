import { Outlet, Navigate, useLocation } from '@umijs/max';
import { Button, Result, Spin } from 'antd';
import { useEffect } from 'react';

import { AdminLayout } from '../app/AdminLayout';
import NotFoundPage from '../components/NotFoundPage';
import {
  adminPath,
  adminRoots,
  adminTitles,
  findAdminRoute,
  safeReturnTarget,
} from '../app/admin-routes';
import { useAdminSession } from './use-admin-session';

export function AdminRouter() {
  const { scope, status, error, refreshSession, hasPermission } =
    useAdminSession();
  const location = useLocation();
  const root = adminRoots[scope];
  const loginPath = adminPath(scope, `${root}/login`);
  const passwordPath = adminPath(scope, `${root}/change-password`);
  const route = findAdminRoute(scope, location.pathname);
  useEffect(() => {
    document.title = `${route?.title ?? '页面不存在'} - ${adminTitles[scope]}`;
  }, [route, scope]);
  if (!route) return <NotFoundPage />;
  if (status === 'loading')
    return (
      <div
        style={{ display: 'grid', placeItems: 'center', minHeight: '100vh' }}
      >
        <Spin description="正在恢复登录状态" size="large">
          <div style={{ padding: 48 }} />
        </Spin>
      </div>
    );
  if (status === 'error')
    return (
      <Result
        status="warning"
        title={error}
        extra={<Button onClick={() => void refreshSession()}>重试</Button>}
      />
    );
  if (status === 'anonymous') {
    if (location.pathname === loginPath) return <Outlet />;
    return (
      <Navigate
        replace
        to={`${loginPath}?return_to=${encodeURIComponent(location.pathname + location.search)}`}
      />
    );
  }
  if (status === 'password_change')
    return location.pathname === passwordPath ? (
      <Outlet />
    ) : (
      <Navigate replace to={passwordPath} />
    );
  if (location.pathname === loginPath)
    return (
      <Navigate
        replace
        to={safeReturnTarget(
          scope,
          new URLSearchParams(location.search).get('return_to'),
        )}
      />
    );
  if (location.pathname === passwordPath)
    return (
      <Navigate replace to={adminPath(scope, `${root}/profile?tab=password`)} />
    );
  return (
    <AdminLayout scope={scope}>
      {route.permission && !hasPermission(route.permission) ? (
        <Result status="403" title="无权访问此页面" />
      ) : (
        <Outlet />
      )}
    </AdminLayout>
  );
}
