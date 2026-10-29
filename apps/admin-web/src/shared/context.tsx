import { createContext, useContext } from 'react';
import type { AdminRequest } from './request';
import type { AdminSession, Community, Scope } from './types';
export interface AdminContextValue {
  scope: Scope;
  request: AdminRequest;
  can: (permission: string) => boolean;
  hasPermission: (permission: string) => boolean;
  session: AdminSession;
  refreshSession: () => Promise<void>;
  company?: { id: string; name: string };
  communityId: string;
  community?: Community;
  communities: Community[];
  go: (page: string, params?: Record<string, string | undefined>) => void;
  page: string;
  params: Record<string, string>;
  setDirty: (dirty: boolean) => void;
  confirmLeave: (action: () => void) => void;
}
export const AdminContext = createContext<AdminContextValue | null>(null);
export function useAdmin() {
  const context = useContext(AdminContext);
  if (!context) throw new Error('后台上下文尚未初始化');
  return context;
}
