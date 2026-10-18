import { vi } from 'vitest';
import type { SessionResponse } from '@/shared/api/admin';
import type {
  Discrepancy,
  PaymentConfiguration,
  PaymentOrder,
  ReconciliationRun,
} from '@/shared/payments/types';
export const companyId = '019a0000-0000-7000-8000-000000000001';
export const paymentId = '019a0000-0000-7000-8000-000000000002';
const timestamp = '2026-10-19T00:00:00Z';
export const payment: PaymentOrder = {
  id: paymentId,
  property_company_id: companyId,
  order_no: 'PAY-TEST-1',
  channel_transaction_no: null,
  merchant_binding_id: companyId,
  rule_version_id: companyId,
  merchant_name: '测试物业',
  merchant_no: '19000001',
  amount_cents: 10000,
  payer_total_cents: 10000,
  status: 'succeeded',
  confirmation_status: 'posted',
  items: [
    {
      id: companyId,
      bill_id: companyId,
      community_id: companyId,
      house_id: companyId,
      house_label: '春日小区101',
      billing_month: '2026-10',
      amount_cents: 10000,
    },
  ],
  expires_at: timestamp,
  paid_at: timestamp,
  closed_at: null,
  created_at: timestamp,
  updated_at: timestamp,
  state_token: 'payment-token-1',
};
export const configuration: PaymentConfiguration = {
  property_company_id: companyId,
  configuration_token: 'configuration-token-1',
  ready: false,
  reasons: ['rule_missing'],
  current_binding: null,
  current_rule: null,
};
export const run: ReconciliationRun = {
  id: companyId,
  business_date: '2026-10-18',
  statement_type: 'trade',
  service_provider_merchant_no: '19000000',
  merchant_no: '19000001',
  status: 'completed',
  projection: 'batch',
  property_company_id: null,
  source_digest: 'sha256:verified',
  summary: {
    local_count: 1,
    channel_count: 1,
    matched_count: 0,
    discrepancy_count: 1,
    local_amount_cents: 10000,
    channel_amount_cents: 10000,
    channel_fee_cents: null,
  },
  created_at: timestamp,
  updated_at: timestamp,
  finished_at: timestamp,
  state_token: 'run-token-1',
};
export const difference: Discrepancy = {
  id: paymentId,
  reconciliation_run_id: companyId,
  property_company_id: companyId,
  difference_type: 'amount_mismatch',
  reference_key: 'payment:PAY-TEST-1:channel_fee',
  payment_order_id: paymentId,
  profit_sharing_order_item_id: null,
  expected_cents: null,
  actual_cents: 60,
  evidence: {
    source: 'channel_trade',
    check_code: 'channel_fee',
    source_digest: 'sha256:verified',
    source_request_id: companyId,
    order_no: payment.order_no,
    channel_transaction_no: null,
    channel_order_no: null,
    channel_detail_no: null,
    statement_line_no: 1,
    expected_status: null,
    actual_status: null,
    checked_at: timestamp,
  },
  status: 'open',
  created_at: timestamp,
  updated_at: timestamp,
  resolved_at: null,
  resolved_by: null,
  resolution_note: null,
  state_token: 'difference-token-1',
};
export function identity(
  scope: 'platform_admin' | 'property_admin',
  permissions: string[],
): SessionResponse {
  return {
    scope,
    subject_id: companyId,
    login_name: 'admin',
    display_name: '管理员',
    must_change_password: false,
    csrf_token: 'csrf',
    permissions,
  };
}
export function mockPayments(
  session: SessionResponse,
  mutate?: (
    path: string,
    init?: RequestInit,
  ) => Response | Promise<Response> | undefined,
) {
  const fetcher = vi.fn<typeof fetch>(async (url, init) => {
    const target = new URL(String(url), window.location.origin);
    const path = target.pathname;
    if (path.endsWith('/admin-sessions/current')) return Response.json(session);
    if (path.endsWith('/property-companies/current'))
      return Response.json({ id: companyId, enabled: true, name: '测试物业' });
    const custom = mutate?.(path, init);
    if (custom) return custom;
    const page = (items: unknown[]) =>
      Response.json({ items, total: items.length, page: 1, page_size: 20 });
    if (path.endsWith('/payment-configuration'))
      return Response.json(configuration);
    if (
      path.endsWith('/merchant-bindings') ||
      path.endsWith('/profit-sharing-rule-versions') ||
      path.endsWith('/profit-sharing-orders') ||
      path.endsWith('/payment-unfreeze-orders')
    )
      return page([]);
    if (path.endsWith('/payment-orders')) return page([payment]);
    if (path.endsWith(`/payment-orders/${paymentId}`))
      return Response.json(payment);
    if (path.endsWith('/payment-reconciliation-runs')) return page([run]);
    if (path.endsWith(`/payment-reconciliation-runs/${companyId}`))
      return Response.json(run);
    if (path.endsWith('/payment-reconciliation-discrepancies'))
      return page([difference]);
    if (path.endsWith(`/payment-reconciliation-discrepancies/${paymentId}`))
      return Response.json(difference);
    return new Response(null, { status: 404 });
  });
  vi.stubGlobal('fetch', fetcher);
  return fetcher;
}
