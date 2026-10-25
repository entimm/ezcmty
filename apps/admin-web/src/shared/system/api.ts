import type { AdminRequest } from '../request';
export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}
export type Filters = Record<string, string | number | boolean | undefined>;
export interface AccountInput {
  login_name: string;
  display_name: string;
  password: string;
  role_ids?: string[];
}
export interface RoleSummary {
  id: string;
  code: string;
  name: string;
  enabled: boolean;
  is_system: boolean;
}
export interface Role extends RoleSummary {
  permissions: string[];
  affected_account_count: number;
}
export interface Account {
  id: string;
  scope: 'platform_admin' | 'property_admin';
  login_name: string;
  display_name: string;
  enabled: boolean;
  must_change_password: boolean;
  created_at: string;
  roles: RoleSummary[];
  effective_permissions: string[];
  property_company_id?: string;
}
export interface Permission {
  code: string;
  name: string;
  group: string;
  assignable: boolean;
  level: string;
  requires: string[];
}
export interface Audit {
  id: string;
  property_company_id: string | null;
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

export interface RoleTemplate {
  code: string;
  name: string;
  permissions: string[];
}
export function createSystemApi(request: AdminRequest) {
  const write = <T>(path: string, method: string, data: unknown) =>
    request<T>(path, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
  const queryString = (filters: Filters) => {
    const q = new URLSearchParams();
    Object.entries(filters).forEach(([key, value]) => {
      if (value !== undefined && value !== '') q.set(key, String(value));
    });
    return q.toString();
  };
  return {
    accounts: (filters: Filters) =>
      request<Page<Account>>(`/v1/admin-accounts?${queryString(filters)}`),
    account: (id: string) =>
      request<Account>(`/v1/admin-accounts/${encodeURIComponent(id)}`),
    createAccount: (data: AccountInput) =>
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
    roles: (filters: Filters) =>
      request<Page<Role>>(`/v1/admin-roles?${queryString(filters)}`),
    role: (id: string) =>
      request<Role>(`/v1/admin-roles/${encodeURIComponent(id)}`),
    createRole: (data: { code: string; name: string; permissions: string[] }) =>
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
    templates: () => request<RoleTemplate[]>('/v1/admin-role-templates'),
    audit: (filters: Filters) =>
      request<Page<Audit>>(`/v1/admin-audit-logs?${queryString(filters)}`),
  };
}
