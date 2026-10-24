import { useQuery } from '@tanstack/react-query';
import { useAdmin } from './context';
export function useResource<T>(
  key: readonly unknown[],
  loader: () => Promise<T>,
  enabled = true,
  poll?: number,
) {
  const { scope, session } = useAdmin();
  return useQuery<T, Error>({
    queryKey: [scope, session.subjectId, ...key],
    queryFn: loader,
    enabled,
    retry: false,
    refetchInterval: poll || false,
  });
}
