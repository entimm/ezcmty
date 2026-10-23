import { useMemo, type ReactNode } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { usePropertySession } from '../hooks';
import { createPropertyWorkspaceApi } from '../api';
import { createImportsApi } from '../../../shared/imports/api';
import { ImportsContext } from '../../../shared/imports/runtime';
import type { Filters, ScopeType } from '../../../shared/imports/types';
export function ImportsRuntime({ children }: { children: ReactNode }) {
  const { request, scope, session, hasPermission } = usePropertySession();
  const client = useQueryClient();
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
      community: scopes.community,
      communities: (filters: Filters) =>
        scopes.communities({
          page: Number(filters.page) || 1,
          page_size: Number(filters.page_size) || 100,
          name: typeof filters.name === 'string' ? filters.name : undefined,
        }),
      businessDestination: (
        importType: string,
        target: { type: ScopeType; id: string },
      ) =>
        importType === 'property_fee_bills' && target.type === 'community'
          ? {
              label: '账单管理',
              path: `/property/communities/${encodeURIComponent(target.id)}/bills?view=all`,
              canNavigate: hasPermission('property.bill.read'),
              confirmationNotice:
                '账单创建后立即生效，请核对房屋、月份和金额。',
              prepareNavigation: async () => {
                await Promise.all(
                  ['bills', 'bill-entries', 'bill-operations', 'audit'].map(
                    (key) => client.invalidateQueries({ queryKey: [key] }),
                  ),
                );
              },
            }
          : null,
    };
  }, [request, scope, session?.subjectId, hasPermission, client]);
  return (
    <ImportsContext.Provider value={value}>{children}</ImportsContext.Provider>
  );
}
