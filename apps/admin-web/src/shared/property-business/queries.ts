import {
  useQuery,
  useQueries,
  useQueryClient,
  type UseQueryOptions,
  type InvalidateQueryFilters,
} from '@tanstack/react-query';
import { usePropertyBusiness } from './runtime';

export function usePropertyQuery<T>(options: UseQueryOptions<T, Error>) {
  const { queryIdentity, company } = usePropertyBusiness();
  return useQuery<T, Error>({
    ...options,
    queryKey: [...queryIdentity, company?.id, ...options.queryKey],
    enabled: !!company?.id && options.enabled !== false,
  });
}

export function usePropertyQueries<T>({
  queries,
}: {
  queries: {
    queryKey: readonly unknown[];
    queryFn: () => Promise<T>;
    enabled?: boolean;
  }[];
}) {
  const { queryIdentity, company } = usePropertyBusiness();
  return useQueries({
    queries: queries.map((options) => ({
      ...options,
      queryKey: [...queryIdentity, company?.id, ...options.queryKey],
      enabled: !!company?.id && options.enabled !== false,
    })),
  });
}

export function usePropertyQueryClient() {
  const cache = useQueryClient();
  const { queryIdentity, company } = usePropertyBusiness();
  return {
    invalidateQueries: (filters: InvalidateQueryFilters) =>
      cache.invalidateQueries({
        ...filters,
        queryKey: [...queryIdentity, company?.id, ...(filters.queryKey || [])],
      }),
  };
}
