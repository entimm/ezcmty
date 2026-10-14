import type { AdminRequest } from '../../shared/request-client';
import type {
  Account,
  AccountCreate,
  Audit,
  Page,
  Permission,
  Role,
} from '../../shared/api/admin';
import { queryString } from '../../shared/api/query-string';
import { createJsonWriter } from '../../shared/api/write';

export function createPlatformAdminApi(request: AdminRequest) {
  const write = createJsonWriter(request);
  return {
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
