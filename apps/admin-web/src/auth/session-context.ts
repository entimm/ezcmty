import { createContext } from 'react';

import type { AdminRequest } from '../shared/request-client';

import type {
  AdminScope,
  AdminSession,
  AuthStatus,
} from '../shared/admin-types';

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
