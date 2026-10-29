import { useCallback, useEffect, useMemo, useRef, type ReactNode } from 'react';
import { useAdmin } from '../../shared/context';
import {
  PropertyBusinessProvider,
  type PropertyBusinessApi,
  type PropertyBusinessRuntime,
} from '../../shared/property-business/runtime';
import { createPropertyApi } from './api';

export function PropertyBusinessBoundary({
  children,
}: {
  children: ReactNode;
}) {
  const admin = useAdmin();
  const identity = JSON.stringify([
    admin.scope,
    admin.session.subjectId,
    admin.session.permissions,
    admin.company?.id,
    admin.communityId,
  ]);
  return (
    <PropertyBusinessScope key={identity}>{children}</PropertyBusinessScope>
  );
}

function PropertyBusinessScope({ children }: { children: ReactNode }) {
  const admin = useAdmin();
  const {
    can: adminCan,
    company,
    setDirty: adminSetDirty,
    go: adminGo,
    confirmLeave: adminConfirmLeave,
  } = admin;
  const active = useRef(true);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  const api = useMemo(() => {
    const source = createPropertyApi(admin.request);
    const guard =
      <A extends unknown[], R>(operation: (...args: A) => Promise<R>) =>
      async (...args: A): Promise<R> => {
        if (!active.current || !admin.company?.id)
          throw new Error('原业务范围已失效');
        const result = await operation(...args);
        if (!active.current || !admin.company?.id)
          throw new Error('原业务范围已失效');
        return result;
      };
    return {
      nodes: guard(source.nodes),
      node: guard(source.node),
      saveNode: guard(source.saveNode),
      houseOptions: guard(source.houseOptions),
      houses: guard(source.houses),
      house: guard(source.house),
      saveHouse: guard(source.saveHouse),
      owners: guard(source.owners),
      saveOwner: guard(source.saveOwner),
      bases: guard(source.bases),
      createBasis: guard(source.createBasis),
      calculate: guard(source.calculate),
      bills: guard(source.bills),
      bill: guard(source.bill),
      entries: guard(source.entries),
      operations: guard(source.operations),
      submitBill: guard(
        (
          submission: Parameters<PropertyBusinessApi['submitBill']>[0],
          key: string,
        ) => {
          if (submission.companyId !== admin.company?.id)
            throw new Error('原账务操作公司已失效');
          return source.submitBill(submission, key);
        },
      ),
      billResult: guard(source.billResult),
      claims: guard(source.claims),
      claim: guard(source.claim),
      reviewClaim: guard(source.reviewClaim),
      bindings: guard(source.bindings),
      binding: guard(source.binding),
      revokeBinding: guard(source.revokeBinding),
    } satisfies PropertyBusinessApi;
  }, [admin.request, admin.company?.id]);
  const can = useCallback(
    (action: Parameters<PropertyBusinessRuntime['can']>[0]) =>
      admin.scope === 'property' &&
      !!company?.id &&
      adminCan(`property.${action}`),
    [admin.scope, adminCan, company?.id],
  );
  const setDirty = useCallback(
    (dirty: boolean) => {
      if (active.current) adminSetDirty(dirty);
    },
    [adminSetDirty],
  );
  const go = useCallback(
    (page: string, params?: Record<string, string | undefined>) => {
      if (active.current) adminGo(page, params);
    },
    [adminGo],
  );
  const confirmLeave = useCallback(
    (action: () => void) => {
      if (active.current)
        adminConfirmLeave(() => {
          if (active.current) action();
        });
    },
    [adminConfirmLeave],
  );
  const runtime: PropertyBusinessRuntime = {
    api,
    can,
    company: admin.company,
    communityId: admin.communityId,
    community: admin.community,
    queryIdentity: [
      admin.scope,
      admin.session.subjectId,
      admin.session.permissions,
    ],
    params: admin.params,
    go,
    setDirty,
    confirmLeave,
  };
  return (
    <PropertyBusinessProvider runtime={runtime}>
      {children}
    </PropertyBusinessProvider>
  );
}
