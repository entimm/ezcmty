import { useState, type ReactNode } from 'react';

import {
  AdminSessionContext,
  type AdminScope,
  type AdminSession,
} from './session-context';

export function SessionProvider({
  children,
  scope,
}: {
  children: ReactNode;
  scope: AdminScope;
}) {
  const [session, setCurrentSession] = useState<AdminSession | null>(null);

  function setSession(value: AdminSession | null) {
    if (value && value.scope !== scope) {
      throw new Error('Session scope does not match this application');
    }
    setCurrentSession(value);
  }

  return (
    <AdminSessionContext.Provider
      value={{
        scope,
        session,
        setSession,
        hasPermission: (permission) =>
          session?.permissions.includes(permission) ?? false,
      }}
    >
      {children}
    </AdminSessionContext.Provider>
  );
}
