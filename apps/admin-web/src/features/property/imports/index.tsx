import { useMemo } from 'react';
import { canImport } from '../../../shared/imports/authorization';
import { useAdmin } from '../../../shared/context';
import { ImportsPage } from '../../../shared/imports/ImportsPage';
import { createImportsApi } from '../../../shared/imports/api';
import type { FlowPageProps } from '../../../shared/imports/runtime';
export function PropertyImportsPage(props: FlowPageProps) {
  const admin = useAdmin();
  const api = useMemo(() => createImportsApi(admin.request), [admin.request]);
  return (
    <ImportsPage
      {...props}
      runtime={{
        scope: 'property',
        api,
        community: admin.community,
        communityId: admin.communityId,
        can: (action, type) => canImport('property', admin.can, action, type),
        setDirty: admin.setDirty,
        company: async () => {
          const value = await admin.request<{
            property_company_id: string;
            property_company_name: string;
          }>('/v1/property-workspace/context');
          return {
            id: value.property_company_id,
            name: value.property_company_name,
          };
        },
      }}
    />
  );
}
