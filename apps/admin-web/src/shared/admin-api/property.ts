import type { AdminRequest } from '../request-client';
import { queryString, type Account, type Page } from './index';

export interface PropertyCompany {
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
export interface PropertyAdmin extends Account {
  scope: 'property_admin';
  property_company_id: string;
}
export interface CompanyCreate {
  code: string;
  name: string;
  contact_name?: string | null;
  contact_phone?: string | null;
}
export interface CommunityCreate {
  code: string;
  name: string;
  address: string;
  property_company_id: string;
}
export interface PropertyAdminCreate {
  login_name: string;
  display_name: string;
  password: string;
}
type Filters = Record<string, string | number | boolean | undefined>;

export function createPropertyApi(request: AdminRequest) {
  const companyPath = (id: string) =>
    `/v1/property-companies/${encodeURIComponent(id)}`;
  const accountPath = (companyId: string, id: string) =>
    `${companyPath(companyId)}/admin-accounts/${encodeURIComponent(id)}`;
  const write = <T>(path: string, method: string, data: unknown) =>
    request<T>(path, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
  return {
    currentCompany: () =>
      request<PropertyCompany>('/v1/property-companies/current'),
    companies: (filters: Filters) =>
      request<Page<PropertyCompany>>(
        `/v1/property-companies?${queryString(filters)}`,
      ),
    company: (id: string) => request<PropertyCompany>(companyPath(id)),
    createCompany: (data: CompanyCreate) =>
      write<PropertyCompany>('/v1/property-companies', 'POST', data),
    updateCompany: (
      id: string,
      data: Omit<Partial<CompanyCreate>, 'code'> & { enabled?: boolean },
    ) => write<PropertyCompany>(companyPath(id), 'PATCH', data),
    communities: (filters: Filters) =>
      request<Page<Community>>(`/v1/communities?${queryString(filters)}`),
    community: (id: string) =>
      request<Community>(`/v1/communities/${encodeURIComponent(id)}`),
    createCommunity: (data: CommunityCreate) =>
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
    admins: (companyId: string, filters: Filters) =>
      request<Page<PropertyAdmin>>(
        `${companyPath(companyId)}/admin-accounts?${queryString(filters)}`,
      ),
    admin: (companyId: string, id: string) =>
      request<PropertyAdmin>(accountPath(companyId, id)),
    createAdmin: (companyId: string, data: PropertyAdminCreate) =>
      write<PropertyAdmin>(
        `${companyPath(companyId)}/admin-accounts`,
        'POST',
        data,
      ),
    updateAdmin: (
      companyId: string,
      id: string,
      data: { display_name?: string; enabled?: boolean },
    ) => write<PropertyAdmin>(accountPath(companyId, id), 'PATCH', data),
    resetAdminPassword: (companyId: string, id: string, password: string) =>
      write<void>(`${accountPath(companyId, id)}/password-resets`, 'POST', {
        password,
      }),
  };
}
