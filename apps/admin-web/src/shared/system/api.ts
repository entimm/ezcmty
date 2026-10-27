import type { components } from '../../../../../openapi/types';
import type { AdminRequest } from '../request';
import type { Page } from '../types';

export type { Page } from '../types';
export type Filters = Record<string, string | number | boolean | undefined>;
export type AccountInput = components['schemas']['AccountCreate'];
export type RoleSummary = components['schemas']['RoleSummary'];
export type Role = components['schemas']['AdminRole'];
export type Account = components['schemas']['AdminAccount'];
export type Permission = components['schemas']['AdminPermission'];
export type Audit = components['schemas']['AuditEntry'];
export type RoleTemplate = components['schemas']['AdminRoleTemplate'];

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
    updateAccount: (id: string, data: components['schemas']['AccountUpdate']) =>
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
    createRole: (data: components['schemas']['RoleCreate']) =>
      write<Role>('/v1/admin-roles', 'POST', data),
    updateRole: (id: string, data: components['schemas']['RoleUpdate']) =>
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
