import { useMemo } from 'react';
import { useAdminSession } from '../../auth/use-admin-session';
import { createPropertyWorkspaceApi } from './api';

export function usePropertySession() {
  const session = useAdminSession();
  if (session.scope !== 'property_admin')
    throw new Error('Property business requires a property application');
  return session;
}

export function usePropertyWorkspaceApi() {
  const { request } = usePropertySession();
  return useMemo(() => createPropertyWorkspaceApi(request), [request]);
}
