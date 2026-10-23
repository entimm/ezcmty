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
      ) => {
        if (target.type !== 'community') return null;
        const destination =
          importType === 'property_fee_bills'
            ? {
                label: '账单管理',
                path: `/property/communities/${encodeURIComponent(target.id)}/bills?view=all`,
                permission: 'property.bill.read',
                notice: '账单创建后立即生效，请核对房屋、月份和金额。',
                queries: ['bills', 'bill-entries', 'bill-operations', 'audit'],
              }
            : importType === 'houses'
              ? {
                  label: '房屋管理',
                  path: `/property/communities/${encodeURIComponent(target.id)}/houses`,
                  permission: 'property.house.read',
                  notice:
                    '本次在目标小区内仅新增房屋。请提前建立分区、楼栋和单元，文件不携带业主信息；已有房屋与当前资料一致则跳过，不同则报冲突。',
                  queries: ['houses', 'audit'],
                }
              : importType === 'house_owners'
                ? {
                    label: '房屋管理',
                    path: `/property/communities/${encodeURIComponent(target.id)}/houses`,
                    permission: 'property.house.read',
                    notice:
                      '本次在目标小区内仅新增业主登记；同一房屋下已有同姓名、同规范化手机号的登记（含停用记录）将跳过，停用记录不会自动启用。不创建房屋、居民账号或房屋授权。',
                    queries: ['house-owners', 'houses', 'audit'],
                  }
                : null;
        if (!destination) return null;
        return {
          label: destination.label,
          path: destination.path,
          canNavigate: hasPermission(destination.permission),
          confirmationNotice: destination.notice,
          prepareNavigation: async () => {
            await Promise.all(
              destination.queries.map((key) =>
                client.invalidateQueries({ queryKey: [key] }),
              ),
            );
          },
        };
      },
    };
  }, [request, scope, session?.subjectId, hasPermission, client]);
  return (
    <ImportsContext.Provider value={value}>{children}</ImportsContext.Provider>
  );
}
