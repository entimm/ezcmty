import type { AdminRequest } from '../../../shared/request-client';
import type { Page } from '../../../shared/api/admin';
import { queryString } from '../../../shared/api/query-string';
import type {
  Discrepancy,
  Filters,
  MerchantBinding,
  PaymentConfiguration,
  PaymentOrder,
  ReconciliationRun,
  RuleVersion,
  SharingOrder,
  UnfreezeOrder,
} from '../../../shared/payments/types';
export function createPropertyPaymentsApi(request: AdminRequest) {
  const scopedQuery = (filters: Filters) =>
    queryString(
      Object.fromEntries(
        Object.entries(filters).filter(
          ([key]) => key !== 'property_company_id',
        ),
      ),
    );
  return {
    configuration: () =>
      request<PaymentConfiguration>('/v1/payment-configuration'),
    bindings: (filters: Filters) =>
      request<Page<MerchantBinding>>(
        `/v1/merchant-bindings?${scopedQuery(filters)}`,
      ),
    rules: (filters: Filters) =>
      request<Page<RuleVersion>>(
        `/v1/profit-sharing-rule-versions?${scopedQuery(filters)}`,
      ),
    rule: (id: string) =>
      request<RuleVersion>(
        `/v1/profit-sharing-rule-versions/${encodeURIComponent(id)}`,
      ),
    orders: (filters: Filters) =>
      request<Page<PaymentOrder>>(`/v1/payment-orders?${scopedQuery(filters)}`),
    order: (id: string) =>
      request<PaymentOrder>(`/v1/payment-orders/${encodeURIComponent(id)}`),
    sharing: (filters: Filters) =>
      request<Page<SharingOrder>>(
        `/v1/profit-sharing-orders?${scopedQuery(filters)}`,
      ),
    unfreezing: (filters: Filters) =>
      request<Page<UnfreezeOrder>>(
        `/v1/payment-unfreeze-orders?${scopedQuery(filters)}`,
      ),
    runs: (filters: Filters) =>
      request<Page<ReconciliationRun>>(
        `/v1/payment-reconciliation-runs?${scopedQuery(filters)}`,
      ),
    run: (id: string) =>
      request<ReconciliationRun>(
        `/v1/payment-reconciliation-runs/${encodeURIComponent(id)}`,
      ),
    discrepancies: (filters: Filters) =>
      request<Page<Discrepancy>>(
        `/v1/payment-reconciliation-discrepancies?${scopedQuery(filters)}`,
      ),
    discrepancy: (id: string) =>
      request<Discrepancy>(
        `/v1/payment-reconciliation-discrepancies/${encodeURIComponent(id)}`,
      ),
  };
}
