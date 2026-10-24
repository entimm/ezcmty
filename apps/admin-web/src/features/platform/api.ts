import type { AdminRequest } from '../../shared/request';

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}
export interface Company {
  id: string;
  code: string;
  name: string;
  contact_name: string | null;
  contact_phone: string | null;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}
export interface Community {
  id: string;
  property_company_id: string;
  property_company_name: string;
  code: string;
  name: string;
  address: string;
  enabled: boolean;
  created_at: string;
  updated_at: string;
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
  property_company_id?: string;
}
export interface Permission {
  code: string;
  name: string;
  group: string;
  assignable: boolean;
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
export interface CompanyInput {
  code: string;
  name: string;
  contact_name?: string | null;
  contact_phone?: string | null;
}
export interface CommunityInput {
  property_company_id: string;
  code: string;
  name: string;
  address: string;
}
export interface AccountInput {
  login_name: string;
  display_name: string;
  password: string;
  role_ids?: string[];
}
export type Filters = Record<string, string | number | boolean | undefined>;

export function queryString(filters: Filters) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters))
    if (value !== undefined && value !== '') params.set(key, String(value));
  return params.toString();
}

export function createPlatformApi(request: AdminRequest) {
  const companyPath = (id: string) =>
    `/v1/property-companies/${encodeURIComponent(id)}`;
  const adminPath = (company: string, id: string) =>
    `${companyPath(company)}/admin-accounts/${encodeURIComponent(id)}`;
  const write = <T>(path: string, method: string, data: unknown) =>
    request<T>(path, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
  return {
    companies: (filters: Filters) =>
      request<Page<Company>>(`/v1/property-companies?${queryString(filters)}`),
    company: (id: string) => request<Company>(companyPath(id)),
    createCompany: (data: CompanyInput) =>
      write<Company>('/v1/property-companies', 'POST', data),
    updateCompany: (
      id: string,
      data: Partial<Omit<CompanyInput, 'code'>> & { enabled?: boolean },
    ) => write<Company>(companyPath(id), 'PATCH', data),
    communities: (filters: Filters) =>
      request<Page<Community>>(`/v1/communities?${queryString(filters)}`),
    community: (id: string) =>
      request<Community>(`/v1/communities/${encodeURIComponent(id)}`),
    createCommunity: (data: CommunityInput) =>
      write<Community>('/v1/communities', 'POST', data),
    updateCommunity: (
      id: string,
      data: Partial<Pick<Community, 'name' | 'address' | 'enabled'>>,
    ) =>
      write<Community>(
        `/v1/communities/${encodeURIComponent(id)}`,
        'PATCH',
        data,
      ),
    companyAdmins: (company: string, filters: Filters) =>
      request<Page<Account>>(
        `${companyPath(company)}/admin-accounts?${queryString(filters)}`,
      ),
    companyAdmin: (company: string, id: string) =>
      request<Account>(adminPath(company, id)),
    createCompanyAdmin: (
      company: string,
      data: Omit<AccountInput, 'role_ids'>,
    ) => write<Account>(`${companyPath(company)}/admin-accounts`, 'POST', data),
    updateCompanyAdmin: (
      company: string,
      id: string,
      data: { display_name?: string; enabled?: boolean },
    ) => write<Account>(adminPath(company, id), 'PATCH', data),
    resetCompanyAdminPassword: (
      company: string,
      id: string,
      password: string,
    ) =>
      write<void>(`${adminPath(company, id)}/password-resets`, 'POST', {
        password,
      }),
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
    audit: (filters: Filters) =>
      request<Page<Audit>>(`/v1/admin-audit-logs?${queryString(filters)}`),
  };
}
export type PlatformApi = ReturnType<typeof createPlatformApi>;
