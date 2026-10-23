import { useMemo, type ReactNode } from 'react';
import { usePlatformSession } from '../hooks';
import { createPropertyOnboardingApi } from '../property/api';
import { createImportsApi } from '../../../shared/imports/api';
import { ImportsContext } from '../../../shared/imports/runtime';
export function ImportsRuntime({ children }: { children: ReactNode }) {
  const { request, scope, session, hasPermission } = usePlatformSession();
  const value = useMemo(() => {
    const scopes = createPropertyOnboardingApi(request);
    return {
      pageRoot: '/platform/imports',
      api: createImportsApi(request),
      scope,
      subjectId: session?.subjectId || '',
      can: (action: string) => hasPermission(`platform.import.${action}`),
      companies: scopes.companies,
      communities: scopes.communities,
      community: scopes.community,
    };
  }, [request, scope, session?.subjectId, hasPermission]);
  return (
    <ImportsContext.Provider value={value}>{children}</ImportsContext.Provider>
  );
}
