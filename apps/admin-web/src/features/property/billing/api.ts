import type { Page } from '../../../shared/api/admin';
import { queryString } from '../../../shared/api/query-string';
import { createJsonWriter } from '../../../shared/api/write';
import type { AdminRequest } from '../../../shared/request-client';

export type HouseUsage = 'residential' | 'commercial' | 'office' | 'other';
export interface FeeBasis {
  id: string;
  house_id: string;
  version_no: number;
  effective_from_month: string;
  house_usage: HouseUsage;
  area_sqm: string | null;
  unit_price_cents: number | null;
  fixed_amount_cents: number | null;
  change_reason: string;
  created_by: string;
  created_at: string;
}
export interface BasisInput {
  expected_latest_version_no: number;
  effective_from_month: string;
  house_usage: HouseUsage;
  area_sqm?: string | null;
  unit_price_cents?: number | null;
  fixed_amount_cents?: number | null;
  change_reason: string;
}
export interface Calculation {
  available: boolean;
  billing_month: string;
  period_start: string;
  period_end: string;
  house_label_snapshot: string;
  basis: FeeBasis | null;
  calculation_method: 'fixed' | 'area_rate' | null;
  calculation_rule_version: number | null;
  receivable_cents: number | null;
}
export interface Bill {
  id: string;
  property_company_id: string;
  community_id: string;
  house_id: string;
  bill_type: 'property_fee';
  period_granularity: 'month';
  billing_month: string;
  period_start: string;
  period_end: string;
  external_bill_no: string | null;
  basis_version_id: string | null;
  amount_source: 'basis' | 'manual';
  calculation_rule_version: number | null;
  receivable_cents: number;
  settled_cents: number;
  outstanding_cents: number;
  lifecycle_status: 'active' | 'voided';
  settlement_status: 'unpaid' | 'partially_settled' | 'settled' | null;
  due_date: string | null;
  is_overdue: boolean;
  house_label_snapshot: string;
  manual_amount_reason: string | null;
  void_reason: string | null;
  voided_at: string | null;
  voided_by: string | null;
  row_version: number;
  created_by: string;
  created_at: string;
  updated_at: string;
  basis: FeeBasis | null;
  house_effective_enabled: boolean;
  payment_in_progress: boolean;
}
export type BillAction =
  | 'create'
  | 'update'
  | 'receipt'
  | 'online_receipt'
  | 'correct_receipt'
  | 'reverse_receipt'
  | 'void';
export interface BillOperation {
  id: string;
  bill_id: string;
  action: BillAction;
  bill_version: number;
  actor_type: 'admin' | 'system';
  actor_id: string | null;
  actor_name: string;
  reason: string | null;
  request_id: string;
  created_at: string;
}
export interface SettlementEntry {
  id: string;
  bill_id: string;
  operation_id: string;
  entry_type: 'receipt' | 'reversal';
  source_type: 'offline' | 'online_payment';
  payment_order_item_id: string | null;
  amount_cents: number;
  reverses_entry_id: string | null;
  reversed_by_entry_id: string | null;
  received_on: string | null;
  created_at: string;
  actor_type: 'admin' | 'system';
  actor_id: string | null;
  actor_name: string;
  reason: string | null;
}
export interface BillWriteResult {
  bill: Bill;
  operation: BillOperation;
  settlement_entries: SettlementEntry[];
}
export interface BillSubmission {
  path: string;
  method: 'POST' | 'PATCH';
  body: object;
  label: string;
}
export type Filters = Record<string, string | number | boolean | undefined>;
export const communityRoot = (c: string) =>
  `/v1/communities/${encodeURIComponent(c)}`;
export const billRoot = (c: string, b?: string) =>
  `${communityRoot(c)}/bills${b ? `/${encodeURIComponent(b)}` : ''}`;
export const basisRoot = (c: string, h: string) =>
  `${communityRoot(c)}/houses/${encodeURIComponent(h)}/property-fee-basis-versions`;

function validateSnapshot<T extends { house_label_snapshot: string }>(
  value: T,
): T {
  if (
    !value.house_label_snapshot ||
    [...value.house_label_snapshot].length > 512
  )
    throw new Error('账单位置快照长度无效，请刷新后重试');
  return value;
}
export function createBillingApi(request: AdminRequest) {
  const write = createJsonWriter(request);
  return {
    bases: (c: string, h: string, filters: Filters) =>
      request<Page<FeeBasis>>(`${basisRoot(c, h)}?${queryString(filters)}`),
    createBasis: (c: string, h: string, body: BasisInput) =>
      write<FeeBasis>(basisRoot(c, h), 'POST', body),
    calculate: async (c: string, h: string, month: string) =>
      validateSnapshot(
        await write<Calculation>(
          `${communityRoot(c)}/houses/${encodeURIComponent(h)}/property-fee-calculations`,
          'POST',
          { billing_month: month },
        ),
      ),
    bills: async (c: string, filters: Filters) => {
      const result = await request<Page<Bill>>(
        `${billRoot(c)}?${queryString(filters)}`,
      );
      result.items.forEach(validateSnapshot);
      return result;
    },
    bill: async (c: string, id: string) =>
      validateSnapshot(await request<Bill>(billRoot(c, id))),
    entries: (c: string, id: string, filters: Filters) =>
      request<Page<SettlementEntry>>(
        `${billRoot(c, id)}/settlement-entries?${queryString(filters)}`,
      ),
    operations: (c: string, id: string, filters: Filters) =>
      request<Page<BillOperation>>(
        `${billRoot(c, id)}/operations?${queryString(filters)}`,
      ),
    submit: async (submission: BillSubmission, key: string) => {
      const result = await request<BillWriteResult>(submission.path, {
        method: submission.method,
        headers: { 'Content-Type': 'application/json', 'Idempotency-Key': key },
        body: JSON.stringify(submission.body),
      });
      validateSnapshot(result.bill);
      return result;
    },
    result: (key: string) =>
      request<{ response_status: number; result: BillWriteResult }>(
        `/v1/bill-operation-results/${encodeURIComponent(key)}`,
        { cache: 'no-store' },
      ),
  };
}
