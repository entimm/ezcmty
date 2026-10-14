import type { Page } from '../../shared/api/admin';
import type { Community, PropertyCompany } from '../../shared/api/property';
import { queryString } from '../../shared/api/query-string';
import type { AdminRequest } from '../../shared/request-client';

export interface CommunityFilters {
  page: number;
  page_size: number;
  name?: string;
  code?: string;
  enabled?: boolean;
}

export function createPropertyWorkspaceApi(request: AdminRequest) {
  return {
    currentCompany: () =>
      request<PropertyCompany>('/v1/property-companies/current'),
    communities: (filters: CommunityFilters) =>
      request<Page<Community>>(
        `/v1/communities?${queryString({
          page: filters.page,
          page_size: filters.page_size,
          name: filters.name,
          code: filters.code,
          enabled: filters.enabled,
        })}`,
      ),
    community: (id: string) =>
      request<Community>(`/v1/communities/${encodeURIComponent(id)}`),
  };
}
