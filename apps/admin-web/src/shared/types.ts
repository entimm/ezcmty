export type Scope = 'platform' | 'property';
export type AdminScope = 'platform_admin' | 'property_admin';
export interface AdminSession {
  scope: AdminScope;
  subjectId: string;
  loginName: string;
  displayName: string;
  permissions: string[];
  mustChangePassword: boolean;
  csrfToken: string;
}
export interface SessionResponse {
  scope: AdminScope;
  subject_id: string;
  login_name: string;
  display_name: string;
  permissions: string[];
  must_change_password: boolean;
  csrf_token: string;
}
export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}
export interface Community {
  id: string;
  property_company_id: string;
  property_company_name?: string;
  code: string;
  name: string;
  address?: string;
  enabled: boolean;
  created_at?: string;
  updated_at?: string;
}
export interface Company {
  id: string;
  code: string;
  name: string;
  enabled: boolean;
  contact_name: string | null;
  contact_phone: string | null;
  created_at: string;
  updated_at: string;
}
export interface ProblemDetails {
  type?: string;
  title?: string;
  status: number;
  detail?: string;
  code?: string;
  request_id?: string;
  errors?: { location: (string | number)[]; type: string }[];
}
