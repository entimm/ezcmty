import type { components } from '../../../../../openapi/types';

export type { Page } from '../types';
export type { Filters } from '../imports/types';

type Schemas = components['schemas'];
export type MerchantBinding = Schemas['MerchantBinding'];
export type RuleVersion = Schemas['ProfitSharingRuleVersion'];
export type PaymentConfiguration = Schemas['PaymentConfiguration'];
export type PaymentOrder = Schemas['ManagedPaymentOrder'];
export type SharingOrder = Schemas['ManagedProfitSharingOrder'];
export type UnfreezeOrder = Schemas['ManagedUnfreezeOrder'];
export type ReconciliationRun = Schemas['ManagedReconciliationRun'];
export type Discrepancy = Schemas['ManagedReconciliationDiscrepancy'];
export type RecoveryInput = Schemas['PaymentRecoveryRequest'];
export type ExternalResolutionInput =
  Schemas['ReconciliationExternalResolutionRequest'];
export type RecoveryAccepted = Schemas['PaymentRecoveryAccepted'];
export type BindingInput = Schemas['MerchantBindingCreate'];
export type RuleInput = Schemas['ProfitSharingRuleCreate'];
