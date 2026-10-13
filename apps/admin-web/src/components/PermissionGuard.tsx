import { Result } from 'antd';
import type { ReactNode } from 'react';

import { useAdminSession } from '../auth/use-admin-session';

export function PermissionGuard({
  permission,
  children,
}: {
  permission: string;
  children: ReactNode;
}) {
  const { session, hasPermission } = useAdminSession();
  if (!session) return <Result status="403" title="请先登录" />;
  if (!hasPermission(permission)) {
    return <Result status="403" title="无权访问此页面" />;
  }
  return children;
}
