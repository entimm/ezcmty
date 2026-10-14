import { createContext } from 'react';

import type { AdminRequest } from '../shared/request-client';

export type AdminScope = 'platform_admin' | 'property_admin';

export interface AdminSession {
  scope: AdminScope;
  subjectId: string;
  permissions: string[];
  loginName: string;
  displayName: string;
  mustChangePassword: boolean;
  csrfToken: string;
}

export type AuthStatus =
  'loading' | 'anonymous' | 'password_change' | 'authenticated' | 'error';

export interface AdminSessionContextValue {
  scope: AdminScope;
  session: AdminSession | null;
  setSession: (session: AdminSession | null) => void;
  hasPermission: (permission: string) => boolean;
  request: AdminRequest;
  status: AuthStatus;
  error: string | null;
  refreshSession: () => Promise<AdminSession | null>;
  login: (loginName: string, password: string) => Promise<AdminSession>;
  logout: () => Promise<void>;
  changePassword: (
    currentPassword: string,
    newPassword: string,
  ) => Promise<void>;
  updateDisplayName: (displayName: string) => void;
}

export const AdminSessionContext =
  createContext<AdminSessionContextValue | null>(null);
