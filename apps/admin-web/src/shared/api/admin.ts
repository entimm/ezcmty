import type { AdminScope } from '../admin-types';

export interface SessionResponse {
  scope: AdminScope;
  subject_id: string;
  login_name: string;
  display_name: string;
  permissions: string[];
  must_change_password: boolean;
  csrf_token: string;
}
export interface Profile {
  id: string;
  scope: AdminScope;
  login_name: string;
  display_name: string;
}
export interface RoleSummary {
  id: string;
  code: string;
  name: string;
  enabled: boolean;
  is_system: boolean;
}
export interface Account {
  id: string;
  scope: AdminScope;
  login_name: string;
  display_name: string;
  enabled: boolean;
  must_change_password: boolean;
  created_at: string;
  roles: RoleSummary[];
}
export interface Role extends RoleSummary {
  permissions: string[];
}
export interface Permission {
  code: string;
  name: string;
  group: string;
  assignable: boolean;
}
export interface Audit {
  id: string;
  property_company_id: string | null;
  actor_id: string | null;
  actor_name: string | null;
  action: string;
  target_type: string;
  target_id: string | null;
  result: 'success' | 'failure';
  request_id: string;
  created_at: string;
  metadata: Record<string, unknown>;
}
export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}
export interface AccountCreate {
  login_name: string;
  display_name: string;
  password: string;
  role_ids: string[];
}
