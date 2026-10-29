import type { components } from '../../../../../openapi/types';

export type { Page } from '../types';
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
export type BillAction =
  'create' | 'edit' | 'receipt' | 'correct' | 'reverse' | 'void';
export interface BillSubmission {
  action: BillAction;
  companyId: string;
  communityId: string;
  billId?: string;
  entryId?: string;
  body: Record<string, unknown>;
}
export type Claim = components['schemas']['PropertyHouseClaim'];
export type ClaimStatus = Claim['status'];
export type Binding = components['schemas']['PropertyHouseBinding'];
export type BindingStatus = Binding['status'];
