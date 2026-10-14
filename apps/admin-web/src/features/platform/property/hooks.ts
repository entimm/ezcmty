import { useMemo } from 'react';
import { useOperation } from '../../../shared/hooks/use-operation';
import { usePlatformSession } from '../hooks';
import { createPropertyOnboardingApi } from './api';

export function usePropertyOnboardingApi() {
  const { request } = usePlatformSession();
  return useMemo(() => createPropertyOnboardingApi(request), [request]);
}
export function usePropertyOnboardingOperation() {
  const { refreshSession } = usePlatformSession();
  return useOperation({
    resources: [
      'property-companies',
      'communities',
      'property-admins',
      'audit',
    ],
    conflictResources: ['property-companies', 'communities', 'property-admins'],
    refreshSession,
  });
}
