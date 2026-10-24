import { useMemo } from 'react';
import { useAdmin } from '../../../shared/context';
import { ImportsPage } from '../../../shared/imports/ImportsPage';
import { createImportsApi } from '../../../shared/imports/api';
import type { Choice, FlowPageProps } from '../../../shared/imports/runtime';
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
        can: (action) => admin.can(`property.import.${action}`),
        setDirty: admin.setDirty,
        company: () => admin.request<Choice>('/v1/property-companies/current'),
      }}
    />
  );
}
