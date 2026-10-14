import type { AdminSession } from '../shared/admin-types';
import type { SessionResponse } from '../shared/api/admin';
import { createJsonWriter } from '../shared/api/write';
import type { AdminRequest } from '../shared/request-client';

function toSession(value: SessionResponse): AdminSession {
  return {
    scope: value.scope,
    subjectId: value.subject_id,
    loginName: value.login_name,
    displayName: value.display_name,
    permissions: value.permissions,
    mustChangePassword: value.must_change_password,
    csrfToken: value.csrf_token,
  };
}

export function createAdminAuthApi(request: AdminRequest) {
  const write = createJsonWriter(request);
  return {
    currentSession: async () =>
      toSession(
        await request<SessionResponse>('/v1/admin-sessions/current', {
          ignoreUnauthorized: true,
          cache: 'no-store',
        }),
      ),
    login: async (login_name: string, password: string) =>
      toSession(
        await request<SessionResponse>('/v1/admin-sessions', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ login_name, password }),
          ignoreUnauthorized: true,
        }),
      ),
    logout: () =>
      request<void>('/v1/admin-sessions/current', { method: 'DELETE' }),
    changePassword: (current_password: string, new_password: string) =>
      write<void>('/v1/admin-accounts/me/password-changes', 'POST', {
        current_password,
        new_password,
      }),
  };
}
