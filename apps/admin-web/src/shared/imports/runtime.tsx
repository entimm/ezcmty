import {
  createContext,
  useContext,
  useState,
  useSyncExternalStore,
  useRef,
} from 'react';
import { useQueryClient } from '@tanstack/react-query';
import type { AdminScope } from '../admin-types';
import { ApiError } from '../request-client';
import {
  pendingSnapshot,
  subscribePending,
  savePending,
  removePending,
} from '../pending-requests';
import type { ImportsApi } from './api';
import type { Filters, Page } from './types';
export interface ScopeOption {
  id: string;
  name: string;
  property_company_id?: string;
}
export interface ImportsRuntime {
  pageRoot: string;
  api: ImportsApi;
  scope: AdminScope;
  subjectId: string;
  can: (action: string) => boolean;
  companies: (filters: Filters) => Promise<Page<ScopeOption>>;
  currentCompany?: () => Promise<ScopeOption>;
  communities: (filters: Filters) => Promise<Page<ScopeOption>>;
}
export const ImportsContext = createContext<ImportsRuntime | null>(null);
export function useImports() {
  const value = useContext(ImportsContext);
  if (!value) throw new Error('导入页面缺少所属后台');
  return value;
}
export interface PendingImport {
  resource: string;
  action: string;
  key: string;
  body: unknown;
}
export function useImportWrite(resource: string) {
  const { scope, subjectId } = useImports();
  const client = useQueryClient();
  const snapshot = useSyncExternalStore(subscribePending, () =>
    pendingSnapshot(scope, subjectId),
  );
  const values = JSON.parse(snapshot) as (string | null)[];
  const pending = values.flatMap((value) => {
    try {
      const item = JSON.parse(value || '') as PendingImport;
      return item.resource === resource && typeof item.key === 'string'
        ? [item]
        : [];
    } catch {
      return [];
    }
  });
  const inFlight = useRef(false);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState<unknown>(null);
  async function run<T>(
    action: string,
    body: unknown,
    execute: (key: string, original: unknown) => Promise<T>,
  ): Promise<T | undefined> {
    if (inFlight.current) return;
    inFlight.current = true;
    const previous = pending.find((item) => item.action === action);
    const value: PendingImport = previous || {
      resource,
      action,
      key: crypto.randomUUID(),
      body,
    };
    setBusy(true);
    setError(null);
    try {
      savePending(scope, subjectId, `imports:${resource}:${action}`, value);
      const result = await execute(value.key, value.body);
      removePending(scope, subjectId, `imports:${resource}:${action}`);
      await client.invalidateQueries({ queryKey: ['imports'] });
      return result;
    } catch (reason) {
      if (reason instanceof ApiError && reason.status < 500)
        removePending(scope, subjectId, `imports:${resource}:${action}`);
      setError(reason);
      await client.invalidateQueries({ queryKey: ['imports'] });
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }
  return { busy, error, pending, run };
}
export function isActive(batch: {
  status: string;
  active_task?: { status: string } | null;
}) {
  return (
    ['uploading', 'prechecking', 'executing', 'cancel_requested'].includes(
      batch.status,
    ) || ['ready', 'running'].includes(batch.active_task?.status || '')
  );
}
export function pollInterval(query: {
  state: { data?: { status: string; active_task?: { status: string } | null } };
  stateUpdateCount?: number;
}) {
  return query.state.data && isActive(query.state.data) ? 3000 : false;
}
