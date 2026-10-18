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
