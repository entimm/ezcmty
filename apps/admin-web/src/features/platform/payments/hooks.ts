import { useMemo } from 'react';
import { usePlatformSession } from '../hooks';
import { useOperation } from '../../../shared/hooks/use-operation';
import { createPlatformPaymentsApi } from './api';
export function usePlatformPaymentsApi() {
  const { request } = usePlatformSession();
  return useMemo(() => createPlatformPaymentsApi(request), [request]);
}
export function usePaymentsOperation() {
  const { refreshSession } = usePlatformSession();
  return useOperation({
    resources: ['payments', 'payment-configuration', 'reconciliation', 'audit'],
    conflictResources: ['payments', 'payment-configuration', 'reconciliation'],
    refreshSession,
  });
}
