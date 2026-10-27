import type { components } from '../../../../../openapi/types';
import type { AdminRequest } from '../../shared/request';
import type { Page } from '../../shared/types';
import { createSystemApi } from '../../shared/system/api';

export type { Page } from '../../shared/types';
export type CompanyOption = components['schemas']['CompanyOption'];
export type Company = components['schemas']['PropertyCompany'];
export type Community = components['schemas']['Community'];
export type PropertyAdminAccount =
  components['schemas']['PropertyAdminAccount'];
export type {
  RoleSummary,
  Role,
  Account,
  Permission,
  Audit,
} from '../../shared/system/api';
export type CompanyInput = components['schemas']['CompanyCreate'];
export type CommunityInput = components['schemas']['CommunityCreate'];
export type AccountInput = components['schemas']['AccountCreate'];
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
    updateCompany: (id: string, data: components['schemas']['CompanyUpdate']) =>
      write<Company>(companyPath(id), 'PATCH', data),
    communities: (filters: Filters) =>
      request<Page<Community>>(`/v1/communities?${queryString(filters)}`),
    community: (id: string) =>
      request<Community>(`/v1/communities/${encodeURIComponent(id)}`),
    createCommunity: (data: CommunityInput) =>
      write<Community>('/v1/communities', 'POST', data),
    updateCommunity: (
      id: string,
      data: components['schemas']['CommunityUpdate'],
    ) =>
      write<Community>(
        `/v1/communities/${encodeURIComponent(id)}`,
        'PATCH',
        data,
      ),
    companyAdmins: (company: string, filters: Filters) =>
      request<Page<PropertyAdminAccount>>(
        `${companyPath(company)}/admin-accounts?${queryString(filters)}`,
      ),
    companyAdmin: (company: string, id: string) =>
      request<PropertyAdminAccount>(adminPath(company, id)),
    createCompanyAdmin: (
      company: string,
      data: components['schemas']['PropertyAdminCreate'],
    ) =>
      write<PropertyAdminAccount>(
        `${companyPath(company)}/admin-accounts`,
        'POST',
        data,
      ),
    updateCompanyAdmin: (
      company: string,
      id: string,
      data: components['schemas']['AccountUpdate'],
    ) => write<PropertyAdminAccount>(adminPath(company, id), 'PATCH', data),
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
