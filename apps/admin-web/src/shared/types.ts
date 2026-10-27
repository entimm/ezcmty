import type { components } from '../../../../openapi/types';

export type Scope = 'platform' | 'property';
export type AdminScope = components['schemas']['AdminSession']['scope'];
export interface AdminSession {
  scope: AdminScope;
  subjectId: string;
  loginName: string;
  displayName: string;
  permissions: string[];
  mustChangePassword: boolean;
  csrfToken: string;
}
export type SessionResponse = components['schemas']['AdminSession'];
export type Page<T> = Omit<components['schemas']['CompanyPage'], 'items'> & {
  items: T[];
};
export type Community = components['schemas']['CommunityOption'];
export type Company = components['schemas']['PropertyCompany'];
// An HTTP error may contain an incomplete Problem Details payload.
export type ProblemDetails = Pick<
  components['schemas']['ProblemDetails'],
  'status'
> &
  Partial<Omit<components['schemas']['ProblemDetails'], 'status'>>;
