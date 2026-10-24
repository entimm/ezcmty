import type { AdminRequest } from '../../shared/request';

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}
export type Filters = Record<
  string,
  string | number | boolean | null | undefined
>;
export interface Community {
  id: string;
  property_company_id: string;
  property_company_name: string;
  code: string;
  name: string;
  address: string;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}
export interface Company {
  id: string;
  code: string;
  name: string;
  contact_name: string | null;
  contact_phone: string | null;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}
export interface WorkspaceSummary {
  billing_month: string;
  pending_house_claims: number | null;
  monthly_receivable_cents: number | null;
  monthly_settled_cents: number | null;
  pending_reconciliation_count: number | null;
}
export type SpaceType = 'phase' | 'building' | 'unit';
export interface HousingRecord {
  id: string;
  enabled: boolean;
  effective_enabled: boolean;
  created_at: string;
  updated_at: string;
}
export interface SpaceAncestor {
  id: string;
  node_type: SpaceType;
  name: string;
}
export interface SpaceNode extends HousingRecord, SpaceAncestor {
  community_id: string;
  parent_id: string | null;
  external_code: string | null;
  sort_order: number;
  has_children: boolean;
  ancestors: SpaceAncestor[];
}
export interface House extends HousingRecord {
  community_id: string;
  space_node_id: string;
  room_no: string;
  floor_no: number | null;
  external_code: string | null;
  display_address: string;
}
export interface Owner extends HousingRecord {
  house_id: string;
  name: string;
  phone: string;
}
export type Usage = 'residential' | 'commercial' | 'office' | 'other';
export interface FeeBasis {
  id: string;
  house_id: string;
  version_no: number;
  effective_from_month: string;
  house_usage: Usage;
  area_sqm: string | null;
  unit_price_cents: number | null;
  fixed_amount_cents: number | null;
  change_reason: string;
  created_by: string;
  created_at: string;
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
  row_version: number;
  created_at: string;
  updated_at: string;
  basis: FeeBasis | null;
  house_effective_enabled: boolean;
  payment_in_progress: boolean;
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
  actor_name: string;
  reason: string | null;
}
export interface BillOperation {
  id: string;
  action:
    | 'create'
    | 'update'
    | 'receipt'
    | 'online_receipt'
    | 'correct_receipt'
    | 'reverse_receipt'
    | 'void';
  actor_name: string;
  reason: string | null;
  created_at: string;
}
export interface BillWriteResult {
  bill: Bill;
  operation: BillOperation;
  settlement_entries: SettlementEntry[];
}
export interface BillSubmission {
  path: string;
  method: 'POST' | 'PATCH';
  body: Record<string, unknown>;
}
export type ClaimStatus = 'pending' | 'approved' | 'rejected' | 'cancelled';
export interface Claim {
  id: string;
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
  reviewed_at: string | null;
  row_version: number;
  created_at: string;
  updated_at: string;
}
export type BindingStatus = 'active' | 'released' | 'revoked';
export interface Binding {
  id: string;
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
}

export function query(filters: Filters = {}) {
  const values = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '')
      values.set(key, String(value));
  });
  return values.toString();
}
export const communityRoot = (id: string) =>
  `/v1/communities/${encodeURIComponent(id)}`;
export const houseRoot = (c: string, h?: string) =>
  `${communityRoot(c)}/houses${h ? `/${encodeURIComponent(h)}` : ''}`;
export const billRoot = (c: string, b?: string) =>
  `${communityRoot(c)}/bills${b ? `/${encodeURIComponent(b)}` : ''}`;

export function createPropertyApi(request: AdminRequest) {
  const read = <T>(path: string, filters: Filters = {}) =>
    request<Page<T>>(`${path}?${query(filters)}`, { cache: 'no-store' });
  const write = <T>(path: string, method: string, body: unknown) =>
    request<T>(path, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  return {
    company: () => request<Company>('/v1/property-companies/current'),
    summary: () => request<WorkspaceSummary>('/v1/property-workspace/summary'),
    communities: (filters: Filters) =>
      read<Community>('/v1/communities', filters),
    community: (id: string) => request<Community>(communityRoot(id)),
    nodes: (c: string, filters: Filters) =>
      read<SpaceNode>(`${communityRoot(c)}/space-nodes`, filters),
    node: (c: string, id: string) =>
      request<SpaceNode>(
        `${communityRoot(c)}/space-nodes/${encodeURIComponent(id)}`,
      ),
    saveNode: (c: string, id: string | undefined, body: unknown) =>
      write<SpaceNode>(
        `${communityRoot(c)}/space-nodes${id ? `/${encodeURIComponent(id)}` : ''}`,
        id ? 'PATCH' : 'POST',
        body,
      ),
    houses: (c: string, filters: Filters) => read<House>(houseRoot(c), filters),
    house: (c: string, id: string) => request<House>(houseRoot(c, id)),
    saveHouse: (c: string, id: string | undefined, body: unknown) =>
      write<House>(houseRoot(c, id), id ? 'PATCH' : 'POST', body),
    owners: (c: string, h: string, filters: Filters) =>
      read<Owner>(`${houseRoot(c, h)}/owners`, filters),
    saveOwner: (c: string, h: string, id: string | undefined, body: unknown) =>
      write<Owner>(
        `${houseRoot(c, h)}/owners${id ? `/${encodeURIComponent(id)}` : ''}`,
        id ? 'PATCH' : 'POST',
        body,
      ),
    bases: (c: string, h: string, filters: Filters) =>
      read<FeeBasis>(`${houseRoot(c, h)}/property-fee-basis-versions`, filters),
    createBasis: (c: string, h: string, body: unknown) =>
      write<FeeBasis>(
        `${houseRoot(c, h)}/property-fee-basis-versions`,
        'POST',
        body,
      ),
    calculate: (c: string, h: string, month: string) =>
      write<Calculation>(
        `${houseRoot(c, h)}/property-fee-calculations`,
        'POST',
        { billing_month: month },
      ),
    bills: (c: string, filters: Filters) => read<Bill>(billRoot(c), filters),
    bill: (c: string, id: string) => request<Bill>(billRoot(c, id)),
    entries: (c: string, id: string, filters: Filters) =>
      read<SettlementEntry>(`${billRoot(c, id)}/settlement-entries`, filters),
    operations: (c: string, id: string, filters: Filters) =>
      read<BillOperation>(`${billRoot(c, id)}/operations`, filters),
    submitBill: (submission: BillSubmission, key: string) =>
      request<BillWriteResult>(submission.path, {
        method: submission.method,
        headers: { 'Content-Type': 'application/json', 'Idempotency-Key': key },
        body: JSON.stringify(submission.body),
      }),
    billResult: (key: string) =>
      request<{ response_status: number; result: BillWriteResult }>(
        `/v1/bill-operation-results/${encodeURIComponent(key)}`,
        { cache: 'no-store' },
      ),
    claims: (filters: Filters) => read<Claim>('/v1/house-claims', filters),
    claim: (id: string) =>
      request<Claim>(`/v1/house-claims/${encodeURIComponent(id)}`, {
        cache: 'no-store',
      }),
    reviewClaim: (id: string, body: unknown) =>
      write<Claim>(
        `/v1/house-claims/${encodeURIComponent(id)}/reviews`,
        'POST',
        body,
      ),
    bindings: (filters: Filters) =>
      read<Binding>('/v1/resident-house-bindings', filters),
    binding: (id: string) =>
      request<Binding>(
        `/v1/resident-house-bindings/${encodeURIComponent(id)}`,
        { cache: 'no-store' },
      ),
    revokeBinding: (id: string, body: unknown) =>
      write<Binding>(
        `/v1/resident-house-bindings/${encodeURIComponent(id)}/revocations`,
        'POST',
        body,
      ),
  };
}
