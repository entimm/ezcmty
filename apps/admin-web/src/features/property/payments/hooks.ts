import { useMemo } from 'react';
import { usePropertySession } from '../hooks';
import { createPropertyPaymentsApi } from './api';
export function usePropertyPaymentsApi() {
  const { request } = usePropertySession();
  return useMemo(() => createPropertyPaymentsApi(request), [request]);
}
