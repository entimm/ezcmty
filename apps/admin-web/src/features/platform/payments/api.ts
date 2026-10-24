import type { AdminRequest } from '../../../shared/request';
import { query } from '../../../shared/imports/api';
import { paymentReads } from '../../../shared/payments/api';
import type {
  PaymentReadApi,
  PlatformPaymentWrites,
} from '../../../shared/payments/runtime';
import type {
  MerchantBinding,
  Page,
  PaymentConfiguration,
  RuleVersion,
} from '../../../shared/payments/types';
export function platformPaymentReads(request: AdminRequest): PaymentReadApi {
  const root = (company?: string) =>
    `/v1/property-companies/${encodeURIComponent(company || '')}`;
  return {
    ...paymentReads(request),
    configuration: (company) =>
      request<PaymentConfiguration>(`${root(company)}/payment-configuration`),
    bindings: (company, filters) =>
      request<Page<MerchantBinding>>(
        `${root(company)}/merchant-bindings?${query(filters)}`,
      ),
    rules: (company, filters) =>
      request<Page<RuleVersion>>(
        `${root(company)}/profit-sharing-rule-versions?${query(filters)}`,
      ),
  };
}
export function platformPaymentWrites(
  request: AdminRequest,
): PlatformPaymentWrites {
  const company = (id: string) =>
    `/v1/property-companies/${encodeURIComponent(id)}`;
  const post = <T>(
    path: string,
    body: unknown,
    key?: string,
    method = 'POST',
  ) =>
    request<T>(path, {
      method,
      headers: {
        'Content-Type': 'application/json',
        ...(key ? { 'Idempotency-Key': key } : {}),
      },
      body: JSON.stringify(body),
    });
  return {
    createBinding: (id, body, key) =>
      post(`${company(id)}/merchant-bindings`, body, key),
    activate: (id, bindingId, token) =>
      post(
        `${company(id)}/active-merchant-binding`,
        { binding_id: bindingId, expected_configuration_token: token },
        undefined,
        'PUT',
      ),
    createRule: (id, body, key) =>
      post(`${company(id)}/profit-sharing-rule-versions`, body, key),
    recover: (id, body) =>
      post(`/v1/payment-orders/${encodeURIComponent(id)}/recoveries`, body),
    recheck: (id, body) =>
      post(
        `/v1/payment-reconciliation-runs/${encodeURIComponent(id)}/rechecks`,
        body,
      ),
    recoverDifference: (id, body) =>
      post(
        `/v1/payment-reconciliation-discrepancies/${encodeURIComponent(id)}/recoveries`,
        body,
      ),
    externalResolution: (id, body) =>
      post(
        `/v1/payment-reconciliation-discrepancies/${encodeURIComponent(id)}/external-resolutions`,
        body,
      ),
  };
}
