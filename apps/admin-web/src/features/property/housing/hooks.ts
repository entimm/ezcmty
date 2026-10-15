import { useMemo } from 'react';
import { usePropertySession } from '../hooks';
import { useOperation } from '../../../shared/hooks/use-operation';
import { createHousingApi } from './api';

export function useHousingApi() {
  const { request } = usePropertySession();
  return useMemo(() => createHousingApi(request), [request]);
}
export function useHousingOperation() {
  const { refreshSession } = usePropertySession();
  return useOperation({
    resources: ['spaces', 'houses', 'house-owners', 'audit'],
    conflictResources: ['spaces', 'houses', 'house-owners'],
    refreshSession,
  });
}
