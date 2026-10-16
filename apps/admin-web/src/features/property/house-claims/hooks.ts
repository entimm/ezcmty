import { useMemo } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { ApiError } from '../../../shared/request-client';
import { usePropertySession } from '../hooks';
import { createHouseClaimsApi } from './api';

export function useHouseClaimsApi() {
  const { request } = usePropertySession();
  return useMemo(() => createHouseClaimsApi(request), [request]);
}

export function useClaimDecision() {
  const client = useQueryClient();
  const { refreshSession } = usePropertySession();
  const invalidate = () =>
    Promise.all(
      ['house-claims', 'resident-house-bindings', 'audit'].map((key) =>
        client.invalidateQueries({ queryKey: [key] }),
      ),
    );
  const operation = useMutation({
    mutationFn: (run: () => Promise<unknown>) => run(),
    retry: false,
    gcTime: 0,
    onSuccess: invalidate,
    onError: async (error) => {
      if (
        !(error instanceof ApiError) ||
        error.status >= 500 ||
        error.status === 409
      )
        await invalidate();
      if (error instanceof ApiError && error.status === 403)
        await refreshSession();
    },
  });
  return { ...operation, invalidate };
}
