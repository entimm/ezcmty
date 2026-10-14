import type { AdminScope, AdminSession } from '../../auth/session-context';
import type { AdminRequest } from '../request-client';

export interface SessionResponse {
  scope: AdminScope;
  subject_id: string;
  login_name: string;
  display_name: string;
  permissions: string[];
  must_change_password: boolean;
  csrf_token: string;
}
export const toSession = (value: SessionResponse): AdminSession => ({
  scope: value.scope,
  subjectId: value.subject_id,
  loginName: value.login_name,
  displayName: value.display_name,
  permissions: value.permissions,
  mustChangePassword: value.must_change_password,
  csrfToken: value.csrf_token,
});
export interface Profile {
  id: string;
  scope: AdminScope;
  login_name: string;
  display_name: string;
}
export interface RoleSummary {
  id: string;
  code: string;
  name: string;
  enabled: boolean;
  is_system: boolean;
}
export interface Account {
  id: string;
  scope: AdminScope;
  login_name: string;
  display_name: string;
  enabled: boolean;
  must_change_password: boolean;
  created_at: string;
  roles: RoleSummary[];
}
export interface Role extends RoleSummary {
  permissions: string[];
}
export interface Permission {
  code: string;
  name: string;
  group: string;
  assignable: boolean;
}
export interface Audit {
  id: string;
  actor_id: string | null;
  actor_name: string | null;
  action: string;
  target_type: string;
  target_id: string | null;
  result: 'success' | 'failure';
  request_id: string;
  created_at: string;
  metadata: Record<string, unknown>;
}
export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}
export interface AccountCreate {
  login_name: string;
  display_name: string;
  password: string;
  role_ids: string[];
}

export function queryString(
  filters: Record<string, string | number | boolean | undefined>,
) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters))
    if (value !== undefined && value !== '') params.set(key, String(value));
  return params.toString();
}

export function createAdminApi(request: AdminRequest) {
  const write = <T>(path: string, method: string, data?: unknown) =>
    request<T>(path, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: data === undefined ? undefined : JSON.stringify(data),
    });
  return {
    profile: () => request<Profile>('/v1/admin-accounts/me'),
    updateProfile: (display_name: string) =>
      write<Profile>('/v1/admin-accounts/me', 'PATCH', { display_name }),
    accounts: (
      filters: Record<string, string | number | boolean | undefined>,
    ) => request<Page<Account>>(`/v1/admin-accounts?${queryString(filters)}`),
    account: (id: string) =>
      request<Account>(`/v1/admin-accounts/${encodeURIComponent(id)}`),
    createAccount: (data: AccountCreate) =>
      write<Account>('/v1/admin-accounts', 'POST', data),
    updateAccount: (
      id: string,
      data: { display_name?: string; enabled?: boolean },
    ) =>
      write<Account>(
        `/v1/admin-accounts/${encodeURIComponent(id)}`,
        'PATCH',
        data,
      ),
    assignRoles: (id: string, role_ids: string[]) =>
      write<Account>(
        `/v1/admin-accounts/${encodeURIComponent(id)}/roles`,
        'PUT',
        { role_ids },
      ),
    resetPassword: (id: string, password: string) =>
      write<void>(
        `/v1/admin-accounts/${encodeURIComponent(id)}/password-resets`,
        'POST',
        { password },
      ),
    roles: (filters: Record<string, string | number | boolean | undefined>) =>
      request<Page<Role>>(`/v1/admin-roles?${queryString(filters)}`),
    role: (id: string) =>
      request<Role>(`/v1/admin-roles/${encodeURIComponent(id)}`),
    createRole: (data: { code: string; name: string }) =>
      write<Role>('/v1/admin-roles', 'POST', data),
    updateRole: (id: string, data: { name?: string; enabled?: boolean }) =>
      write<Role>(`/v1/admin-roles/${encodeURIComponent(id)}`, 'PATCH', data),
    assignPermissions: (id: string, permissions: string[]) =>
      write<Role>(
        `/v1/admin-roles/${encodeURIComponent(id)}/permissions`,
        'PUT',
        { permissions },
      ),
    permissions: () => request<Permission[]>('/v1/admin-permissions'),
    audit: (filters: Record<string, string | number | boolean | undefined>) =>
      request<Page<Audit>>(`/v1/admin-audit-logs?${queryString(filters)}`),
  };
}
