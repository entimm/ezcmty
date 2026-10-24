export type { Page, Filters } from '../imports/types';
export interface MerchantBinding {
  id: string;
  property_company_id: string;
  service_provider_merchant_no: string;
  merchant_no: string;
  merchant_name: string;
  enabled: boolean;
  max_ratio_bps: number | null;
  ratio_checked_at: string | null;
  row_version: number;
  created_at: string;
  updated_at: string;
}
export interface RuleVersion {
  id: string;
  property_company_id: string;
  version_no: number;
  calculation_version: 1;
  items: {
    id: string;
    receiver_type: 'merchant';
    receiver_account: string;
    receiver_name: string;
    relation_type: 'service_provider';
    rate_bps: number;
  }[];
  created_at: string;
}
export interface PaymentConfiguration {
  property_company_id: string;
  configuration_token: string;
  ready: boolean;
  reasons: string[];
  current_binding: MerchantBinding | null;
  current_rule: RuleVersion | null;
}
export interface PaymentOrder {
  id: string;
  property_company_id: string;
  order_no: string;
  channel_transaction_no: string | null;
  merchant_binding_id: string;
  rule_version_id: string;
  merchant_name: string;
  merchant_no: string;
  amount_cents: number;
  payer_total_cents: number | null;
  status:
    'pending' | 'unknown' | 'payable' | 'closing' | 'succeeded' | 'closed';
  confirmation_status: 'unconfirmed' | 'awaiting_posting' | 'posted';
  items: {
    id: string;
    bill_id: string;
    community_id: string;
    house_id: string;
    house_label: string;
    billing_month: string;
    amount_cents: number;
  }[];
  expires_at: string;
  paid_at: string | null;
  closed_at: string | null;
  created_at: string;
  updated_at: string;
  state_token: string;
}
export interface SharingOrder {
  id: string;
  property_company_id: string;
  payment_order_id: string;
  order_no: string;
  channel_order_no: string | null;
  status: 'pending' | 'unknown' | 'processing' | 'finished' | 'rejected';
  created_at: string;
  updated_at: string;
  items: {
    id: string;
    allocation_id: string;
    receiver_type: 'merchant';
    receiver_account: string;
    receiver_name: string;
    allocation_cents: number;
    amount_cents: number;
    result: 'success' | 'failed' | null;
    channel_detail_no: string | null;
    failure_summary: string | null;
    finished_at: string | null;
  }[];
}
export interface UnfreezeOrder {
  id: string;
  property_company_id: string;
  payment_order_id: string;
  order_no: string;
  channel_order_no: string | null;
  status:
    | 'pending'
    | 'unknown'
    | 'processing'
    | 'succeeded'
    | 'failed'
    | 'no_remaining';
  unfrozen_cents: number | null;
  channel_detail_no: string | null;
  failure_summary: string | null;
  finished_at: string | null;
  created_at: string;
  updated_at: string;
}
export interface ReconciliationRun {
  id: string;
  business_date: string;
  statement_type: 'trade' | 'profit_sharing' | 'platform_fundflow';
  service_provider_merchant_no: string;
  merchant_no: string | null;
  status: 'ready' | 'running' | 'completed' | 'failed';
  projection: 'batch' | 'company';
  property_company_id: string | null;
  source_digest: string | null;
  summary: {
    local_count: number;
    channel_count: number;
    matched_count: number;
    discrepancy_count: number;
    local_amount_cents: number | null;
    channel_amount_cents: number | null;
    channel_fee_cents: number | null;
  };
  created_at: string;
  updated_at: string;
  finished_at: string | null;
  state_token: string;
}
export interface Discrepancy {
  id: string;
  reconciliation_run_id: string;
  property_company_id: string | null;
  difference_type:
    | 'channel_only'
    | 'local_only'
    | 'amount_mismatch'
    | 'status_mismatch'
    | 'unclassified';
  reference_key: string;
  payment_order_id: string | null;
  profit_sharing_order_item_id: string | null;
  expected_cents: number | null;
  actual_cents: number | null;
  evidence: {
    source: string;
    check_code: string;
    source_digest: string | null;
    source_request_id: string | null;
    order_no: string | null;
    channel_transaction_no: string | null;
    channel_order_no: string | null;
    channel_detail_no: string | null;
    statement_line_no: number | null;
    expected_status: string | null;
    actual_status: string | null;
    checked_at: string;
  };
  status: 'open' | 'observing' | 'resolved';
  created_at: string;
  updated_at: string;
  resolved_at: string | null;
  resolved_by: string | null;
  resolution_note: string | null;
  state_token: string;
}
export interface RecoveryInput {
  reason: string;
  expected_state_token: string;
}
export interface ExternalResolutionInput extends RecoveryInput {
  evidence_reference: string;
}
export interface RecoveryAccepted {
  target_type: string;
  target_id: string;
  accepted_at: string;
}
export interface BindingInput {
  merchant_no: string;
  merchant_name: string;
  expected_configuration_token: string;
}
export interface RuleInput {
  expected_configuration_token: string;
  items: [{ rate_bps: number }];
}
