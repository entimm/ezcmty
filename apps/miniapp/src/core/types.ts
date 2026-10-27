import type { components } from '../../../../openapi/types';

type Schemas = components['schemas'];

export type User = Schemas['MiniappUser'];
export type Session = Schemas['ResidentSession'];
export type SessionState = Schemas['ResidentSessionState'];
export type PageResult<T> = Omit<Schemas['PhoneBindingPage'], 'items'> & {
  items: T[];
};
export type PhoneBinding = Schemas['PhoneBinding'];
export type Community = Schemas['ClaimableCommunity'];
export type SpaceNode = Schemas['ClaimableSpaceNode'];
export type House = Schemas['ClaimableHouse'];
export type Claim = Schemas['ResidentHouseClaim'];
export type ClaimStatus = Claim['status'];
export type Binding = Schemas['ResidentHouseBinding'];
export type BindingStatus = Binding['status'];
export type ClaimInput = Schemas['HouseClaimCreate'];
export type ResidentBill = Schemas['ResidentBill'];
export type SettlementEntry = Schemas['ResidentBillSettlementEntry'];
export type PaymentStatus = Schemas['ResidentPaymentStatus'];
export type ConfirmationStatus = Schemas['ResidentPaymentConfirmationStatus'];
export type PaymentOrder = Schemas['ResidentPaymentOrder'];
export type PaymentAction = PaymentOrder['available_actions'][number];
export type PaymentInput = Schemas['ResidentPaymentOrderCreate'];
export type ClientParameters = Schemas['ResidentClientPaymentParameters'];
