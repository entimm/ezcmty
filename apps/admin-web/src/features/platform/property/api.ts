import type { AdminRequest } from '../../../shared/request-client';
import type { Page } from '../../../shared/api/admin';
import type {
  Community,
  CommunityCreate,
  CompanyCreate,
  PropertyAdmin,
  PropertyAdminCreate,
  PropertyCompany,
} from '../../../shared/api/property';
import { queryString } from '../../../shared/api/query-string';
import { createJsonWriter } from '../../../shared/api/write';

type Filters = Record<string, string | number | boolean | undefined>;

export function createPropertyOnboardingApi(request: AdminRequest) {
  const companyPath = (id: string) =>
    `/v1/property-companies/${encodeURIComponent(id)}`;
  const accountPath = (companyId: string, id: string) =>
    `${companyPath(companyId)}/admin-accounts/${encodeURIComponent(id)}`;
  const write = createJsonWriter(request);
  return {
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
