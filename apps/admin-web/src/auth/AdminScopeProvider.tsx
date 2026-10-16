import { ProConfigProvider } from '@ant-design/pro-components';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from 'react';

import { ApiError, createAdminRequestClient } from '../shared/request-client';
import type {
  AdminScope,
  AdminSession,
  AuthStatus,
} from '../shared/admin-types';
import { createAdminAuthApi } from './api';
import { clearPendingRequests } from '../shared/pending-requests';
import { AdminSessionContext } from './session-context';

interface ProviderProps {
  children: ReactNode;
  scope: AdminScope;
  apiBase: string;
  authenticationEnabled?: boolean;
}
interface State {
  session: AdminSession | null;
  status: AuthStatus;
  error: string | null;
  cacheGeneration: number;
}

function ScopedState({
  children,
  scope,
  apiBase,
  authenticationEnabled = false,
}: ProviderProps) {
  const [state, setState] = useState<State>({
    session: null,
    status: authenticationEnabled ? 'loading' : 'anonymous',
    error: null,
    cacheGeneration: 0,
  });
  const sessionRef = useRef<AdminSession | null>(null);
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: { retry: false },
          mutations: { retry: false },
        },
      }),
  );
  const [requestClient] = useState(() =>
    createAdminRequestClient({
      scope,
      basePath: apiBase,
      onUnauthorized: () => setSession(null),
      getCsrfToken: () => sessionRef.current?.csrfToken,
      onPasswordChangeRequired: () => {
        if (sessionRef.current)
          setSession({ ...sessionRef.current, mustChangePassword: true });
      },
    }),
  );

  const [api] = useState(() => createAdminAuthApi(requestClient.request));

  function setSession(value: AdminSession | null) {
    if (value && value.scope !== scope)
      throw new Error('Session scope does not match this application');
    if (
      sessionRef.current &&
      (!value || sessionRef.current.subjectId !== value.subjectId)
    )
      clearPendingRequests(scope, sessionRef.current.subjectId);
    requestClient.cancel();
    void queryClient.cancelQueries();
    queryClient.clear();
    sessionRef.current = value;
    setState((previous) => ({
      session: value,
      status: value
        ? value.mustChangePassword
          ? 'password_change'
          : 'authenticated'
        : 'anonymous',
      error: null,
      cacheGeneration: previous.cacheGeneration + 1,
    }));
  }

  const refreshSession = useCallback(async () => {
    try {
      const value = await api.currentSession();
      if (value.scope !== scope) throw new Error('后台身份不匹配');
      if (
        sessionRef.current?.subjectId !== value.subjectId ||
        sessionRef.current?.csrfToken !== value.csrfToken ||
        sessionRef.current?.mustChangePassword !== value.mustChangePassword
      ) {
        if (
          sessionRef.current &&
          sessionRef.current.subjectId !== value.subjectId
        )
          clearPendingRequests(scope, sessionRef.current.subjectId);
        requestClient.cancel();
        void queryClient.cancelQueries();
        queryClient.clear();
        sessionRef.current = value;
        setState((previous) => ({
          session: value,
          status: value.mustChangePassword
            ? 'password_change'
            : 'authenticated',
          error: null,
          cacheGeneration: previous.cacheGeneration + 1,
        }));
      } else {
        sessionRef.current = value;
        setState((previous) => ({
          ...previous,
          session: value,
          status: value.mustChangePassword
            ? 'password_change'
            : 'authenticated',
          error: null,
        }));
      }
      return value;
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError')
        return null;
      if (error instanceof ApiError && error.status === 401) {
        requestClient.cancel();
        void queryClient.cancelQueries();
        queryClient.clear();
        if (sessionRef.current)
          clearPendingRequests(scope, sessionRef.current.subjectId);
        sessionRef.current = null;
        setState((previous) => ({
          session: null,
          status: 'anonymous',
          error: null,
          cacheGeneration: previous.cacheGeneration + 1,
        }));
      } else {
        setState((previous) => ({
          ...previous,
          status: 'error',
          error: '无法确认登录状态，请重试',
        }));
      }
      return null;
    }
  }, [scope, api, requestClient, queryClient]);

  useEffect(() => {
    const timer = authenticationEnabled
      ? window.setTimeout(() => void refreshSession(), 0)
      : undefined;
    return () => {
      if (timer !== undefined) window.clearTimeout(timer);
      requestClient.cancel();
      queryClient.clear();
    };
  }, [authenticationEnabled, refreshSession, requestClient, queryClient]);

  return (
    <AdminSessionContext.Provider
      value={{
        scope,
        session: state.session,
        status: state.status,
        error: state.error,
        setSession,
        refreshSession,
        hasPermission: (permission) =>
          state.session?.permissions.includes(permission) ?? false,
        request: requestClient.request,
        login: async (login_name, password) => {
          const value = await api.login(login_name, password);
          setSession(value);
          return value;
        },
        logout: async () => {
          await api.logout();
          setSession(null);
        },
        changePassword: async (current_password, new_password) => {
          await api.changePassword(current_password, new_password);
          setSession(null);
        },
        updateDisplayName: (displayName) => {
          if (!sessionRef.current) return;
          const value = { ...sessionRef.current, displayName };
          sessionRef.current = value;
          setState((previous) => ({ ...previous, session: value }));
        },
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
  return <ScopedState key={`${props.scope}:${props.apiBase}`} {...props} />;
}
