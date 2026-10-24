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
export interface PageResult<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
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
export interface ResidentBill {
  id: string;
  property_company_id: string;
  property_company_name: string;
  community_id: string;
  house_id: string;
  house_label_snapshot: string;
  bill_type: 'property_fee';
  billing_month: string;
  period_start: string;
  period_end: string;
  receivable_cents: number;
  settled_cents: number;
  outstanding_cents: number;
  lifecycle_status: 'active' | 'voided';
  settlement_status: 'unpaid' | 'partially_settled' | 'settled' | null;
  due_date: string | null;
  is_overdue: boolean;
  row_version: number;
  payment_availability:
    | 'available'
    | 'own_payment_in_progress'
    | 'other_payment_in_progress'
    | 'settled'
    | 'voided'
    | 'collection_unavailable';
  own_payment_order_id: string | null;
  created_at: string;
  updated_at: string;
}
export interface SettlementEntry {
  id: string;
  bill_id: string;
  entry_type: 'receipt' | 'reversal';
  source_type: 'offline' | 'online_payment';
  amount_cents: number;
  received_on: string | null;
  display_type:
    'own_payment' | 'other_payment' | 'offline_receipt' | 'offline_adjustment';
  own_payment_order_id: string | null;
  created_at: string;
}
export type PaymentStatus =
  'pending' | 'unknown' | 'payable' | 'closing' | 'succeeded' | 'closed';
export type ConfirmationStatus = 'unconfirmed' | 'awaiting_posting' | 'posted';
export type PaymentAction = 'continue_payment' | 'refresh' | 'close';
export interface PaymentInput {
  items: [{ bill_id: string; expected_row_version: number }];
}
export interface PaymentOrder {
  id: string;
  order_no: string;
  merchant_name: string;
  amount_cents: number;
  payer_total_cents: number | null;
  status: PaymentStatus;
  confirmation_status: ConfirmationStatus;
  available_actions: PaymentAction[];
  items: {
    id: string;
    bill_id: string;
    bill_type: 'property_fee';
    billing_month: string;
    house_label_snapshot: string;
    amount_cents: number;
  }[];
  expires_at: string;
  paid_at: string | null;
  closed_at: string | null;
  created_at: string;
  updated_at: string;
}
export interface ClientParameters {
  payment_order_id: string;
  channel: 'wechat_pay';
  client_parameters: {
    timeStamp: string;
    nonceStr: string;
    package: string;
    signType: 'RSA';
    paySign: string;
  };
}
