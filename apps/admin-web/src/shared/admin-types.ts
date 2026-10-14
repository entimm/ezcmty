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
