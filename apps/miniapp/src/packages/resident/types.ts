export interface Community {
  id: string;
  name: string;
  address: string;
}
export interface SpaceNode {
  id: string;
  community_id: string;
  parent_id: string | null;
  name: string;
  node_type: 'phase' | 'building' | 'unit';
  has_children: boolean;
}
export interface House {
  id: string;
  community_id: string;
  space_node_id: string;
  room_no: string;
  display_address: string;
}
export type ClaimStatus = 'pending' | 'approved' | 'rejected' | 'cancelled';
export type BindingStatus = 'active' | 'released' | 'revoked';
export interface Claim {
  id: string;
  community_id: string;
  house_id: string;
  house_label_snapshot: string;
  applicant_name: string;
  applicant_phone: string;
  applicant_remark: string | null;
  status: ClaimStatus;
  review_reason: string | null;
  reviewed_at: string | null;
  cancelled_at: string | null;
  row_version: number;
  created_at: string;
  updated_at: string;
}
export interface Binding {
  id: string;
  community_id: string;
  house_id: string;
  claim_application_id: string;
  house_label_snapshot: string;
  status: BindingStatus;
  effective_enabled: boolean;
  granted_at: string;
  ended_at: string | null;
  end_reason: string | null;
  row_version: number;
  created_at: string;
  updated_at: string;
}
export interface ClaimInput {
  house_id: string;
  applicant_name: string;
  phone_binding_id: string;
  applicant_remark: string | null;
}
