import { useMemo } from 'react';
import { useAdminSession } from '../../../auth/use-admin-session';
import { createPropertyApi } from '../../../shared/admin-api/property';
import { useAdminOperation } from '../hooks';

export function usePropertyApi() {
  const { request } = useAdminSession();
  return useMemo(() => createPropertyApi(request), [request]);
}
export function usePropertyOperation() {
  return useAdminOperation([
    'property-companies',
    'communities',
    'property-admins',
    'audit',
  ]);
}

export function parseEnabled(value: string | null) {
  return value === 'true' ? true : value === 'false' ? false : undefined;
}
