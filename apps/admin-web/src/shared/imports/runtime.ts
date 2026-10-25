import type { ImportsApi } from './api';
export interface Choice {
  id: string;
  name: string;
  property_company_id?: string;
}
export interface ImportsRuntime {
  scope: 'platform' | 'property';
  api: ImportsApi;
  can: (action: string, type?: string) => boolean;
  community?: Choice;
  communityId: string;
  company?: () => Promise<Choice>;
  companies?: () => Promise<Choice[]>;
  communities?: (companyId: string) => Promise<Choice[]>;
  setDirty: (dirty: boolean) => void;
}
export interface FlowPageProps {
  page: string;
  params: Record<string, string>;
  go: (page: string, params?: Record<string, string | undefined>) => void;
}
