import { useMemo } from 'react';
import { canImport } from '../../../shared/imports/authorization';
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
        can: (action, type) => canImport('platform', admin.can, action, type),
        setDirty: admin.setDirty,
        companies: () =>
          allOptions((page) =>
            admin.request<Page<Choice>>(
              `/v1/property-company-options?page=${page}&page_size=100`,
            ),
          ),
        communities: (company) =>
          allOptions((page) =>
            admin.request<Page<Choice>>(
              `/v1/community-options?page=${page}&page_size=100&property_company_id=${encodeURIComponent(company)}`,
            ),
          ),
      }}
    />
  );
}
