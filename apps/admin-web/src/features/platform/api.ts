import type { AdminRequest } from '../../shared/request';

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}
export interface CompanyOption {
  id: string;
  name: string;
  enabled: boolean;
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
export type {
  RoleSummary,
  Role,
  Account,
  Permission,
  Audit,
} from '../../shared/system/api';
import type { Account } from '../../shared/system/api';
import { createSystemApi } from '../../shared/system/api';
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
    companyOptions: (filters: Filters) =>
      request<Page<CompanyOption>>(
        `/v1/property-company-options?${queryString(filters)}`,
      ),
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
    ...createSystemApi(request),
  };
}
export type PlatformApi = ReturnType<typeof createPlatformApi>;
