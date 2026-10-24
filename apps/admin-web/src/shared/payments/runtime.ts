import type { paymentReads } from './api';
import type {
  BindingInput,
  Discrepancy,
  ExternalResolutionInput,
  Filters,
  MerchantBinding,
  Page,
  PaymentConfiguration,
  RecoveryAccepted,
  RecoveryInput,
  RuleInput,
  RuleVersion,
} from './types';
import type { Choice } from '../imports/runtime';
export interface PaymentReadApi extends ReturnType<typeof paymentReads> {
  configuration: (company?: string) => Promise<PaymentConfiguration>;
  bindings: (
    company: string | undefined,
    filters: Filters,
  ) => Promise<Page<MerchantBinding>>;
  rules: (
    company: string | undefined,
    filters: Filters,
  ) => Promise<Page<RuleVersion>>;
}
export interface PlatformPaymentWrites {
  createBinding: (
    company: string,
    body: BindingInput,
    key: string,
  ) => Promise<MerchantBinding>;
  activate: (
    company: string,
    bindingId: string | null,
    token: string,
  ) => Promise<PaymentConfiguration>;
  createRule: (
    company: string,
    body: RuleInput,
    key: string,
  ) => Promise<RuleVersion>;
  recover: (id: string, body: RecoveryInput) => Promise<RecoveryAccepted>;
  recheck: (id: string, body: RecoveryInput) => Promise<RecoveryAccepted>;
  recoverDifference: (
    id: string,
    body: RecoveryInput,
  ) => Promise<RecoveryAccepted>;
  externalResolution: (
    id: string,
    body: ExternalResolutionInput,
  ) => Promise<Discrepancy>;
}
export interface PaymentsRuntime {
  scope: 'platform' | 'property';
  api: PaymentReadApi;
  writes?: PlatformPaymentWrites;
  can: (permission: string) => boolean;
  communityId: string;
  community?: Choice;
  companies?: () => Promise<Choice[]>;
  setDirty: (dirty: boolean) => void;
}
