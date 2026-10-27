import type { components } from '../../../../../openapi/types';
import type { AdminRequest } from '../../shared/request';
import type { Page } from '../../shared/types';

export type { Page } from '../../shared/types';
export type Filters = Record<
  string,
  string | number | boolean | null | undefined
>;
export type Community = components['schemas']['Community'];
export type Company = components['schemas']['PropertyCompany'];
export type WorkspaceSummary =
  components['schemas']['PropertyWorkspaceSummary'];
export type SpaceType = components['schemas']['SpaceNode']['node_type'];
export type HousingRecord = Pick<
  components['schemas']['SpaceNode'],
  'id' | 'enabled' | 'effective_enabled' | 'created_at' | 'updated_at'
>;
export type SpaceAncestor = components['schemas']['SpaceAncestor'];
export type SpaceNode = components['schemas']['SpaceNode'];
export type House = components['schemas']['House'];
export type HouseOption = components['schemas']['HouseOption'];
export type Owner = components['schemas']['HouseOwner'];
export type Usage = components['schemas']['FeeBasisVersion']['house_usage'];
export type FeeBasis = components['schemas']['FeeBasisVersion'];
export type Calculation = components['schemas']['FeeCalculation'];
export type Bill = components['schemas']['Bill'];
export type SettlementEntry = components['schemas']['SettlementEntry'];
export type BillOperation = components['schemas']['BillOperation'];
export type BillWriteResult = components['schemas']['BillWriteResult'];
export interface BillSubmission {
  path: string;
  method: 'POST' | 'PATCH';
  body: Record<string, unknown>;
}
export type Claim = components['schemas']['PropertyHouseClaim'];
export type ClaimStatus = Claim['status'];
export type Binding = components['schemas']['PropertyHouseBinding'];
export type BindingStatus = Binding['status'];

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
    houseOptions: (c: string, filters: Filters) =>
      read<HouseOption>(`${communityRoot(c)}/house-options`, filters),
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
      request<components['schemas']['BillOperationResult']>(
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
