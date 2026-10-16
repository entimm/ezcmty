import { useMemo, useSyncExternalStore } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { usePropertySession } from '../hooks';
import { ApiError } from '../../../shared/request-client';
import {
  pendingSnapshot,
  removePending,
  savePending,
  subscribePending,
} from '../../../shared/pending-requests';
import {
  createBillingApi,
  type BillSubmission,
  type BillWriteResult,
} from './api';

export interface PendingBillWrite extends BillSubmission {
  key: string;
  submittedAt: string;
  kind: 'bill';
}
export function useBillingApi() {
  const { request } = usePropertySession();
  return useMemo(() => createBillingApi(request), [request]);
}
export function usePendingBills(): PendingBillWrite[] {
  const { scope, session } = usePropertySession();
  const snapshot = useSyncExternalStore(
    subscribePending,
    () => pendingSnapshot(scope, session?.subjectId ?? ''),
    () => '[]',
  );
  return useMemo(
    () =>
      (JSON.parse(snapshot) as (string | null)[]).flatMap((value) => {
        try {
          const item = value ? (JSON.parse(value) as PendingBillWrite) : null;
          return item?.kind === 'bill' && typeof item.key === 'string'
            ? [item]
            : [];
        } catch {
          return [];
        }
      }),
    [snapshot],
  );
}
export function useBillingWrite() {
  const api = useBillingApi();
  const { scope, session, refreshSession } = usePropertySession();
  const client = useQueryClient();
  const invalidate = async () => {
    await Promise.all(
      ['bills', 'bill-entries', 'bill-operations', 'audit'].map((key) =>
        client.invalidateQueries({ queryKey: [key] }),
      ),
    );
  };
  const mutation = useMutation({
    retry: false,
    mutationFn: async ({
      submission,
      recovery,
    }: {
      submission: BillSubmission;
      recovery?: PendingBillWrite;
    }): Promise<BillWriteResult> => {
      if (!session) throw new Error('请重新登录');
      const pending: PendingBillWrite = recovery ?? {
        ...submission,
        key: crypto.randomUUID(),
        submittedAt: new Date().toISOString(),
        kind: 'bill',
      };
      savePending(scope, session.subjectId, pending.key, pending);
      try {
        const result = await api.submit(pending, pending.key);
        removePending(scope, session.subjectId, pending.key);
        await invalidate();
        return result;
      } catch (error) {
        if (error instanceof ApiError && error.status < 500) {
          if (!recovery) removePending(scope, session.subjectId, pending.key);
          if (error.status === 409) await invalidate();
          if (error.status === 403) await refreshSession();
        }
        throw error;
      }
    },
  });
  return { ...mutation, invalidate };
}
