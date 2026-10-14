import { useMemo } from 'react';
import { useAdminSession } from '../../auth/use-admin-session';
import type { Profile } from '../../shared/api/admin';
import { createJsonWriter } from '../../shared/api/write';
import type { AdminRequest } from '../../shared/request-client';

export function createProfileApi(request: AdminRequest) {
  const write = createJsonWriter(request);
  return {
    profile: () => request<Profile>('/v1/admin-accounts/me'),
    updateProfile: (display_name: string) =>
      write<Profile>('/v1/admin-accounts/me', 'PATCH', { display_name }),
  };
}

export function useProfileApi() {
  const { request } = useAdminSession();
  return useMemo(() => createProfileApi(request), [request]);
}
