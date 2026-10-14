import { useMutation, useQueryClient } from '@tanstack/react-query';
import { ApiError } from '../request-client';

export function useOperation({
  resources,
  conflictResources,
  refreshSession,
}: {
  resources: string[];
  conflictResources: string[];
  refreshSession: () => Promise<unknown>;
}) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({
      run,
      security,
    }: {
      run: () => Promise<unknown>;
      security?: boolean;
    }) => {
      const value = await run();
      if (security) await refreshSession();
      await Promise.all(
        resources.map((key) => client.invalidateQueries({ queryKey: [key] })),
      );
      return value;
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 409)
        void Promise.all(
          conflictResources.map((key) =>
            client.invalidateQueries({ queryKey: [key] }),
          ),
        );
    },
    retry: false,
    gcTime: 0,
  });
}
