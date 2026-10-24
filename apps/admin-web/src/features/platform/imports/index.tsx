import { useMemo } from 'react';
import { useAdmin } from '../../../shared/context';
import { ImportsPage } from '../../../shared/imports/ImportsPage';
import { createImportsApi } from '../../../shared/imports/api';
import { allOptions } from '../../../shared/imports/options';
import type { Choice, FlowPageProps } from '../../../shared/imports/runtime';
import type { Page } from '../../../shared/imports/types';
export function PlatformImportsPage(props: FlowPageProps) {
  const admin = useAdmin();
  const api = useMemo(() => createImportsApi(admin.request), [admin.request]);
  return (
    <ImportsPage
      {...props}
      runtime={{
        scope: 'platform',
        api,
        communityId: '',
        can: (action) => admin.can(`platform.import.${action}`),
        setDirty: admin.setDirty,
        companies: admin.can('property.company.read')
          ? () =>
              allOptions((page) =>
                admin.request<Page<Choice>>(
                  `/v1/property-companies?page=${page}&page_size=100&sort=created_at`,
                ),
              )
          : undefined,
        communities: admin.can('property.community.read')
          ? (company) =>
              allOptions((page) =>
                admin.request<Page<Choice>>(
                  `/v1/communities?page=${page}&page_size=100&property_company_id=${encodeURIComponent(company)}&sort=created_at`,
                ),
              )
          : undefined,
      }}
    />
  );
}
