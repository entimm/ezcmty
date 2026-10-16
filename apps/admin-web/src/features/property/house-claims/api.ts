import type { Page } from '../../../shared/api/admin';
import { queryString } from '../../../shared/api/query-string';
import { createJsonWriter } from '../../../shared/api/write';
import type { AdminRequest } from '../../../shared/request-client';

export type ClaimStatus = 'pending' | 'approved' | 'rejected' | 'cancelled';
export type BindingStatus = 'active' | 'released' | 'revoked';
export interface Claim {
  id: string;
  property_company_id: string;
  user_id: string;
  community_id: string;
  house_id: string;
  house_label_snapshot: string;
  applicant_name: string;
  applicant_phone: string;
  applicant_remark: string | null;
  status: ClaimStatus;
  match_status: 'matched' | 'unmatched';
  matched_owner_id: string | null;
  review_reason: string | null;
  reviewed_by_admin_id: string | null;
  reviewed_at: string | null;
  cancelled_at: string | null;
  row_version: number;
  created_at: string;
  updated_at: string;
}
export interface HouseBinding {
  id: string;
  property_company_id: string;
  user_id: string;
  community_id: string;
  house_id: string;
  claim_application_id: string;
  house_label_snapshot: string;
  applicant_name: string;
  applicant_phone: string;
  status: BindingStatus;
  effective_enabled: boolean;
  granted_at: string;
  ended_at: string | null;
  end_reason: string | null;
  row_version: number;
  created_at: string;
  updated_at: string;
}
export interface ReviewInput {
  expected_row_version: number;
  decision: 'approved' | 'rejected';
  reason?: string;
}
export interface RevocationInput {
  expected_row_version: number;
  reason: string;
}
type Filters = Record<string, string | number | undefined>;

export function createHouseClaimsApi(request: AdminRequest) {
  const claim = (id: string) => `/v1/house-claims/${encodeURIComponent(id)}`;
  const binding = (id: string) =>
    `/v1/resident-house-bindings/${encodeURIComponent(id)}`;
  const readOptions = { cache: 'no-store' as const };
  const write = createJsonWriter(request);
  return {
    claims: (filters: Filters) =>
      request<Page<Claim>>(
        `/v1/house-claims?${queryString(filters)}`,
        readOptions,
      ),
    claim: (id: string) => request<Claim>(claim(id), readOptions),
    review: (id: string, data: ReviewInput) =>
      write<Claim>(`${claim(id)}/reviews`, 'POST', data),
    bindings: (filters: Filters) =>
      request<Page<HouseBinding>>(
        `/v1/resident-house-bindings?${queryString(filters)}`,
        readOptions,
      ),
    binding: (id: string) => request<HouseBinding>(binding(id), readOptions),
    revoke: (id: string, data: RevocationInput) =>
      write<HouseBinding>(`${binding(id)}/revocations`, 'POST', data),
  };
}
