import { createContext, useContext, type ReactNode } from 'react';
import type {
  Bill,
  BillOperation,
  BillSubmission,
  BillWriteResult,
  Binding,
  Calculation,
  Claim,
  FeeBasis,
  Filters,
  House,
  HouseOption,
  Owner,
  Page,
  SpaceNode,
} from './types';
import type { components } from '../../../../../openapi/types';

export type PropertyBusinessAction =
  | 'housing.read'
  | 'housing.manage'
  | 'bill.read'
  | 'bill.manage'
  | 'fee_basis.manage'
  | 'bill_receipt.create'
  | 'bill_receipt.correct'
  | 'bill.void'
  | 'resident_access.read'
  | 'resident_access.review'
  | 'resident_access.revoke';

export interface PropertyBusinessApi {
  nodes: (community: string, filters: Filters) => Promise<Page<SpaceNode>>;
  node: (community: string, id: string) => Promise<SpaceNode>;
  saveNode: (
    community: string,
    id: string | undefined,
    body: unknown,
  ) => Promise<SpaceNode>;
  houseOptions: (
    community: string,
    filters: Filters,
  ) => Promise<Page<HouseOption>>;
  houses: (community: string, filters: Filters) => Promise<Page<House>>;
  house: (community: string, id: string) => Promise<House>;
  saveHouse: (
    community: string,
    id: string | undefined,
    body: unknown,
  ) => Promise<House>;
  owners: (
    community: string,
    house: string,
    filters: Filters,
  ) => Promise<Page<Owner>>;
  saveOwner: (
    community: string,
    house: string,
    id: string | undefined,
    body: unknown,
  ) => Promise<Owner>;
  bases: (
    community: string,
    house: string,
    filters: Filters,
  ) => Promise<Page<FeeBasis>>;
  createBasis: (
    community: string,
    house: string,
    body: unknown,
  ) => Promise<FeeBasis>;
  calculate: (
    community: string,
    house: string,
    month: string,
  ) => Promise<Calculation>;
  bills: (community: string, filters: Filters) => Promise<Page<Bill>>;
  bill: (community: string, id: string) => Promise<Bill>;
  entries: (
    community: string,
    bill: string,
    filters: Filters,
  ) => Promise<Page<components['schemas']['SettlementEntry']>>;
  operations: (
    community: string,
    bill: string,
    filters: Filters,
  ) => Promise<Page<BillOperation>>;
  submitBill: (
    submission: BillSubmission,
    key: string,
  ) => Promise<BillWriteResult>;
  billResult: (
    key: string,
  ) => Promise<components['schemas']['BillOperationResult']>;
  claims: (filters: Filters) => Promise<Page<Claim>>;
  claim: (id: string) => Promise<Claim>;
  reviewClaim: (id: string, body: unknown) => Promise<Claim>;
  bindings: (filters: Filters) => Promise<Page<Binding>>;
  binding: (id: string) => Promise<Binding>;
  revokeBinding: (id: string, body: unknown) => Promise<Binding>;
}

export interface PropertyBusinessRuntime {
  api: PropertyBusinessApi;
  can: (action: PropertyBusinessAction) => boolean;
  company?: { id: string; name: string };
  communityId: string;
  community?: { id: string; name: string; enabled: boolean };
  /** Non-secret identity: caller, authenticated subject and permission snapshot. */
  queryIdentity: readonly unknown[];
  params: Record<string, string>;
  go: (page: string, params?: Record<string, string | undefined>) => void;
  setDirty: (dirty: boolean) => void;
  confirmLeave: (action: () => void) => void;
}

const Context = createContext<PropertyBusinessRuntime | null>(null);
export function PropertyBusinessProvider({
  runtime,
  children,
}: {
  runtime: PropertyBusinessRuntime;
  children: ReactNode;
}) {
  return <Context.Provider value={runtime}>{children}</Context.Provider>;
}
export function usePropertyBusiness() {
  const runtime = useContext(Context);
  if (!runtime) throw new Error('物业业务运行能力尚未提供');
  return runtime;
}
