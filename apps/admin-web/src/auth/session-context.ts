import { createContext } from 'react';

import type { AdminRequest } from '../shared/request-client';

export type AdminScope = 'platform_admin' | 'property_admin';

export interface AdminSession {
  scope: AdminScope;
  subjectId: string;
  permissions: string[];
}

export interface AdminSessionContextValue {
  scope: AdminScope;
  session: AdminSession | null;
  setSession: (session: AdminSession | null) => void;
  hasPermission: (permission: string) => boolean;
  request: AdminRequest;
}

export const AdminSessionContext =
  createContext<AdminSessionContextValue | null>(null);
