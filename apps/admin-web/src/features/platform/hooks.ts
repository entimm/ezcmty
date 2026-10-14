import { useMemo } from 'react';
import { useAdminSession } from '../../auth/use-admin-session';
import { useOperation } from '../../shared/hooks/use-operation';
import { createPlatformAdminApi } from './api';

export function usePlatformSession() {
  const session = useAdminSession();
  if (session.scope !== 'platform_admin')
    throw new Error('Platform business requires a platform application');
  return session;
}
export function usePlatformAdminApi() {
  const { request } = usePlatformSession();
  return useMemo(() => createPlatformAdminApi(request), [request]);
}
export function usePlatformAdminOperation() {
  const { refreshSession } = usePlatformSession();
  return useOperation({
    resources: ['accounts', 'roles', 'audit'],
    conflictResources: ['accounts', 'roles'],
    refreshSession,
  });
}
