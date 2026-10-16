export interface User {
  id: string;
  enabled: boolean;
  created_at: string;
  last_login_at: string;
}
export interface Session {
  token: string;
  expires_at: string;
  user: User;
}
export interface SessionState {
  expires_at: string;
  user: User;
}
export interface PhoneBinding {
  id: string;
  phone: string;
  status: 'active' | 'unbound';
  first_verified_at: string;
  last_verified_at: string;
  unbound_at: string | null;
  row_version: number;
  created_at: string;
  updated_at: string;
}
export interface PageResult<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}
