import { useMemo, type ReactNode } from 'react';
import { usePropertySession } from '../hooks';
import { createPropertyWorkspaceApi } from '../api';
import { createImportsApi } from '../../../shared/imports/api';
import { ImportsContext } from '../../../shared/imports/runtime';
import type { Filters } from '../../../shared/imports/types';
export function ImportsRuntime({ children }: { children: ReactNode }) {
  const { request, scope, session, hasPermission } = usePropertySession();
  const value = useMemo(() => {
    const scopes = createPropertyWorkspaceApi(request);
    return {
      pageRoot: '/property/imports',
      api: createImportsApi(request),
      scope,
      subjectId: session?.subjectId || '',
      can: (action: string) => hasPermission(`property.import.${action}`),
      currentCompany: scopes.currentCompany,
      companies: async () => ({ items: [], total: 0, page: 1, page_size: 100 }),
      communities: (filters: Filters) =>
        scopes.communities({
          page: Number(filters.page) || 1,
          page_size: Number(filters.page_size) || 100,
          name: typeof filters.name === 'string' ? filters.name : undefined,
        }),
    };
  }, [request, scope, session?.subjectId, hasPermission]);
  return (
    <ImportsContext.Provider value={value}>{children}</ImportsContext.Provider>
  );
}
