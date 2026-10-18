import type { AdminRequest } from '../../../shared/request-client';
import type { Page } from '../../../shared/api/admin';
import { queryString } from '../../../shared/api/query-string';
import { createJsonWriter } from '../../../shared/api/write';
import type {
  Discrepancy,
  ExternalResolutionInput,
  Filters,
  MerchantBinding,
  PaymentConfiguration,
  PaymentOrder,
  ReconciliationRun,
  RecoveryAccepted,
  RecoveryInput,
  RuleVersion,
  SharingOrder,
  UnfreezeOrder,
} from '../../../shared/payments/types';
export interface BindingInput {
  merchant_no: string;
  merchant_name: string;
  expected_configuration_token: string;
}
export interface RuleInput {
  expected_configuration_token: string;
  items: [{ rate_bps: number }];
}
export function createPlatformPaymentsApi(request: AdminRequest) {
  const company = (id: string) =>
    `/v1/property-companies/${encodeURIComponent(id)}`;
  const write = createJsonWriter(request);
  const create = <T>(path: string, body: object, key: string) =>
    request<T>(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Idempotency-Key': key },
      body: JSON.stringify(body),
    });
  return {
    configuration: (id: string) =>
      request<PaymentConfiguration>(`${company(id)}/payment-configuration`),
    bindings: (id: string, filters: Filters) =>
      request<Page<MerchantBinding>>(
        `${company(id)}/merchant-bindings?${queryString(filters)}`,
      ),
    rules: (id: string, filters: Filters) =>
      request<Page<RuleVersion>>(
        `${company(id)}/profit-sharing-rule-versions?${queryString(filters)}`,
      ),
    rule: (id: string, version: string) =>
      request<RuleVersion>(
        `${company(id)}/profit-sharing-rule-versions/${encodeURIComponent(version)}`,
      ),
    createBinding: (id: string, body: BindingInput, key: string) =>
      create<MerchantBinding>(`${company(id)}/merchant-bindings`, body, key),
    activate: (
      id: string,
      binding_id: string | null,
      expected_configuration_token: string,
    ) =>
      write<PaymentConfiguration>(
        `${company(id)}/active-merchant-binding`,
        'PUT',
        { binding_id, expected_configuration_token },
      ),
    createRule: (id: string, body: RuleInput, key: string) =>
      create<RuleVersion>(
        `${company(id)}/profit-sharing-rule-versions`,
        body,
        key,
      ),
    orders: (filters: Filters) =>
      request<Page<PaymentOrder>>(`/v1/payment-orders?${queryString(filters)}`),
    order: (id: string) =>
      request<PaymentOrder>(`/v1/payment-orders/${encodeURIComponent(id)}`),
    sharing: (filters: Filters) =>
      request<Page<SharingOrder>>(
        `/v1/profit-sharing-orders?${queryString(filters)}`,
      ),
    unfreezing: (filters: Filters) =>
      request<Page<UnfreezeOrder>>(
        `/v1/payment-unfreeze-orders?${queryString(filters)}`,
      ),
    runs: (filters: Filters) =>
      request<Page<ReconciliationRun>>(
        `/v1/payment-reconciliation-runs?${queryString(filters)}`,
      ),
    run: (id: string) =>
      request<ReconciliationRun>(
        `/v1/payment-reconciliation-runs/${encodeURIComponent(id)}`,
      ),
    discrepancies: (filters: Filters) =>
      request<Page<Discrepancy>>(
        `/v1/payment-reconciliation-discrepancies?${queryString(filters)}`,
      ),
    discrepancy: (id: string) =>
      request<Discrepancy>(
        `/v1/payment-reconciliation-discrepancies/${encodeURIComponent(id)}`,
      ),
    recover: (id: string, body: RecoveryInput) =>
      write<RecoveryAccepted>(
        `/v1/payment-orders/${encodeURIComponent(id)}/recoveries`,
        'POST',
        body,
      ),
    recheck: (id: string, body: RecoveryInput) =>
      write<RecoveryAccepted>(
        `/v1/payment-reconciliation-runs/${encodeURIComponent(id)}/rechecks`,
        'POST',
        body,
      ),
    recoverDifference: (id: string, body: RecoveryInput) =>
      write<RecoveryAccepted>(
        `/v1/payment-reconciliation-discrepancies/${encodeURIComponent(id)}/recoveries`,
        'POST',
        body,
      ),
    externalResolution: (id: string, body: ExternalResolutionInput) =>
      write<Discrepancy>(
        `/v1/payment-reconciliation-discrepancies/${encodeURIComponent(id)}/external-resolutions`,
        'POST',
        body,
      ),
  };
}
