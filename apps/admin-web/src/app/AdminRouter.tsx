import { Outlet, Navigate, useLocation } from '@umijs/max';
import { Button, Result, Spin } from 'antd';
import { useEffect } from 'react';

import { AdminLayout } from './AdminLayout';
import NotFoundPage from '../components/NotFoundPage';
import { useAdminApp } from '../shared/admin-app-context';
import { useAdminSession } from '../auth/use-admin-session';

export function AdminRouter() {
  const { status, error, refreshSession, hasPermission } = useAdminSession();
  const location = useLocation();
  const {
    title,
    loginPath,
    passwordPath,
    profilePath,
    findRoute,
    returnTarget,
  } = useAdminApp();
  const route = findRoute(location.pathname);
  useEffect(() => {
    document.title = `${route?.title ?? '页面不存在'} - ${title}`;
  }, [route, title]);
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
        to={returnTarget(new URLSearchParams(location.search).get('return_to'))}
      />
    );
  if (location.pathname === passwordPath)
    return <Navigate replace to={`${profilePath}?tab=password`} />;
  return (
    <AdminLayout>
      {route.permission && !hasPermission(route.permission) ? (
        <Result status="403" title="无权访问此页面" />
      ) : (
        <Outlet />
      )}
    </AdminLayout>
  );
}
