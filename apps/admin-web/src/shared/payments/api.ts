import type { AdminRequest } from '../request';
import { query } from '../imports/api';
import type {
  Discrepancy,
  Filters,
  Page,
  PaymentOrder,
  ReconciliationRun,
  SharingOrder,
  UnfreezeOrder,
} from './types';
// The shared transport exposes reads only. Platform mutations belong to its runtime.
export function paymentReads(
  request: AdminRequest,
  projectFilters: (filters: Filters) => Filters = (filters) => filters,
) {
  return {
    orders: (filters: Filters) =>
      request<Page<PaymentOrder>>(
        `/v1/payment-orders?${query(projectFilters(filters))}`,
      ),
    order: (id: string) =>
      request<PaymentOrder>(`/v1/payment-orders/${encodeURIComponent(id)}`),
    sharing: (filters: Filters) =>
      request<Page<SharingOrder>>(
        `/v1/profit-sharing-orders?${query(projectFilters(filters))}`,
      ),
    unfreezing: (filters: Filters) =>
      request<Page<UnfreezeOrder>>(
        `/v1/payment-unfreeze-orders?${query(projectFilters(filters))}`,
      ),
    runs: (filters: Filters) =>
      request<Page<ReconciliationRun>>(
        `/v1/payment-reconciliation-runs?${query(projectFilters(filters))}`,
      ),
    run: (id: string) =>
      request<ReconciliationRun>(
        `/v1/payment-reconciliation-runs/${encodeURIComponent(id)}`,
      ),
    discrepancies: (filters: Filters) =>
      request<Page<Discrepancy>>(
        `/v1/payment-reconciliation-discrepancies?${query(projectFilters(filters))}`,
      ),
    discrepancy: (id: string) =>
      request<Discrepancy>(
        `/v1/payment-reconciliation-discrepancies/${encodeURIComponent(id)}`,
      ),
  };
}
