import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  useCallback,
  type ReactNode,
} from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import {
  ApiError,
  createRequestClient,
  type AdminRequest,
} from '../shared/request';
import type { AdminSession, Scope, SessionResponse } from '../shared/types';
type Status =
  'loading' | 'anonymous' | 'password_change' | 'authenticated' | 'error';
interface SessionContextValue {
  scope: Scope;
  status: Status;
  session: AdminSession | null;
  request: AdminRequest;
  error: string;
  refreshSession: () => Promise<void>;
  login: (name: string, password: string) => Promise<AdminSession>;
  logout: () => Promise<void>;
  changePassword: (current: string, next: string) => Promise<void>;
  updateName: (name: string) => void;
}
const SessionContext = createContext<SessionContextValue | null>(null);
export const mapSession = (value: SessionResponse): AdminSession => ({
  scope: value.scope,
  subjectId: value.subject_id,
  loginName: value.login_name,
  displayName: value.display_name,
  permissions: value.permissions,
  mustChangePassword: value.must_change_password,
  csrfToken: value.csrf_token,
});
export function SessionProvider({
  scope,
  children,
}: {
  scope: Scope;
  children: ReactNode;
}) {
  const [status, setStatus] = useState<Status>('loading'),
    [session, setSession] = useState<AdminSession | null>(null),
    [error, setError] = useState('');
  const sessionRef = useRef<AdminSession | null>(null);
  const [cache] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: { retry: false, refetchOnWindowFocus: false },
          mutations: { retry: false },
        },
      }),
  );
  const commitRef = useRef<(value: AdminSession | null) => void>(
    () => undefined,
  );
  const [client] = useState(() =>
    createRequestClient({
      scope: scope === 'platform' ? 'platform_admin' : 'property_admin',
      basePath:
        scope === 'platform'
          ? process.env.UMI_APP_PLATFORM_API_BASE || '/api/platform'
          : process.env.UMI_APP_PROPERTY_API_BASE || '/api/property',
      getCsrfToken: () => sessionRef.current?.csrfToken,
      onUnauthorized: () => commitRef.current(null),
      onPasswordChangeRequired: () => {
        if (sessionRef.current)
          commitRef.current({
            ...sessionRef.current,
            mustChangePassword: true,
          });
      },
    }),
  );
  const commit = useCallback(
    (value: AdminSession | null) => {
      if (value && value.scope !== `${scope}_admin`)
        throw new Error('后台身份不匹配');
      client.cancel();
      void cache.cancelQueries();
      cache.clear();
      sessionRef.current = value;
      setSession(value);
      setError('');
      setStatus(
        value
          ? value.mustChangePassword
            ? 'password_change'
            : 'authenticated'
          : 'anonymous',
      );
    },
    [cache, client, scope],
  );
  commitRef.current = commit;
  const refreshSession = useCallback(async () => {
    try {
      const value = mapSession(
        await client.request<SessionResponse>('/v1/admin-sessions/current', {
          ignoreUnauthorized: true,
          cache: 'no-store',
        }),
      );
      if (value.scope !== `${scope}_admin`) throw new Error('后台身份不匹配');
      const old = sessionRef.current;
      if (
        !old ||
        old.subjectId !== value.subjectId ||
        old.csrfToken !== value.csrfToken ||
        old.mustChangePassword !== value.mustChangePassword ||
        [...old.permissions].sort().join('\n') !==
          [...value.permissions].sort().join('\n')
      )
        commit(value);
      else {
        sessionRef.current = value;
        setSession(value);
        setStatus(
          value.mustChangePassword ? 'password_change' : 'authenticated',
        );
        setError('');
      }
    } catch (reason) {
      if (reason instanceof DOMException && reason.name === 'AbortError')
        return;
      if (reason instanceof ApiError && reason.status === 401) commit(null);
      else {
        setError(reason instanceof Error ? reason.message : '无法确认登录状态');
        setStatus('error');
      }
    }
  }, [client, commit, scope]);
  useEffect(() => {
    void refreshSession();
    return () => {
      client.cancel();
      cache.clear();
    };
  }, [refreshSession, client, cache]);
  return (
    <SessionContext.Provider
      value={{
        scope,
        status,
        session,
        request: client.request,
        error,
        refreshSession,
        login: async (name, password) => {
          const value = mapSession(
            await client.request<SessionResponse>('/v1/admin-sessions', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ login_name: name, password }),
              ignoreUnauthorized: true,
            }),
          );
          commit(value);
          return value;
        },
        logout: async () => {
          await client.request<void>('/v1/admin-sessions/current', {
            method: 'DELETE',
          });
          commit(null);
        },
        changePassword: async (current, next) => {
          await client.request<void>('/v1/admin-accounts/me/password-changes', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              current_password: current,
              new_password: next,
            }),
          });
          commit(null);
        },
        updateName: (name) => {
          if (sessionRef.current) {
            const value = { ...sessionRef.current, displayName: name };
            sessionRef.current = value;
            setSession(value);
          }
        },
      }}
    >
      <QueryClientProvider client={cache}>{children}</QueryClientProvider>
    </SessionContext.Provider>
  );
}
export function useSession() {
  const value = useContext(SessionContext);
  if (!value) throw new Error('缺少身份上下文');
  return value;
}
