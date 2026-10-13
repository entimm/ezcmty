import { ProConfigProvider } from '@ant-design/pro-components';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useEffect, useState, type ReactNode } from 'react';

import { adminApiBases } from '../shared/config';
import { createAdminRequestClient } from '../shared/request-client';
import {
  AdminSessionContext,
  type AdminScope,
  type AdminSession,
} from './session-context';

interface ProviderProps {
  children: ReactNode;
  scope: AdminScope;
}

function ScopedState({ children, scope }: ProviderProps) {
  const [state, setState] = useState({
    session: null as AdminSession | null,
    cacheGeneration: 0,
  });
  const [queryClient] = useState(
    () => new QueryClient({ defaultOptions: { queries: { retry: false } } }),
  );
  const [requestClient] = useState(() =>
    createAdminRequestClient({
      scope,
      basePath: adminApiBases[scope],
      onUnauthorized: () => setSession(null),
    }),
  );

  function setSession(value: AdminSession | null) {
    if (value && value.scope !== scope) {
      throw new Error('Session scope does not match this application');
    }
    requestClient.cancel();
    void queryClient.cancelQueries();
    queryClient.clear();
    setState((previous) => ({
      session: value,
      cacheGeneration: previous.cacheGeneration + 1,
    }));
  }

  useEffect(
    () => () => {
      requestClient.cancel();
      queryClient.clear();
    },
    [requestClient, queryClient],
  );

  return (
    <AdminSessionContext.Provider
      value={{
        scope,
        session: state.session,
        setSession,
        hasPermission: (permission) =>
          state.session?.permissions.includes(permission) ?? false,
        request: requestClient.request,
      }}
    >
      <QueryClientProvider client={queryClient}>
        <ProConfigProvider key={state.cacheGeneration} autoClearCache>
          {children}
        </ProConfigProvider>
      </QueryClientProvider>
    </AdminSessionContext.Provider>
  );
}

export function AdminScopeProvider(props: ProviderProps) {
  return <ScopedState key={props.scope} {...props} />;
}
