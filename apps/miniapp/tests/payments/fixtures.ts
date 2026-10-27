import {
  Binding,
  PageResult,
  PaymentOrder,
  ResidentBill,
  SettlementEntry,
} from '../../src/packages/resident/types';

export const billFixture = (
  changes: Partial<ResidentBill> = {},
): ResidentBill => ({
  id: 'bill-1',
  property_company_id: 'company-1',
  property_company_name: '锦城安心物业',
  community_id: 'community-1',
  house_id: 'house-1',
  house_label_snapshot: '梧桐里一期 · 3栋1单元1202室',
  bill_type: 'property_fee',
  billing_month: '2026-10-01',
  period_start: '2026-10-01',
  period_end: '2026-10-31',
  receivable_cents: 20000,
  settled_cents: 0,
  outstanding_cents: 20000,
  lifecycle_status: 'active',
  settlement_status: 'unpaid',
  due_date: '2026-10-31',
  is_overdue: false,
  row_version: 4,
  payment_availability: 'available',
  own_payment_order_id: null,
  created_at: '2026-10-01T00:00:00Z',
  updated_at: '2026-10-01T00:00:00Z',
  ...changes,
});
export const orderFixture = (
  changes: Partial<PaymentOrder> = {},
): PaymentOrder => ({
  id: 'order-1',
  order_no: 'PN202610240001',
  merchant_name: '锦城安心物业',
  amount_cents: 20000,
  payer_total_cents: null,
  status: 'payable',
  confirmation_status: 'unconfirmed',
  available_actions: ['continue_payment', 'refresh', 'close'],
  items: [
    {
      id: 'item-1',
      bill_id: 'bill-1',
      bill_type: 'property_fee',
      billing_month: '2026-10-01',
      house_label_snapshot: '梧桐里一期 · 3栋1单元1202室',
      amount_cents: 20000,
    },
  ],
  expires_at: '2026-10-24T02:15:00Z',
  paid_at: null,
  closed_at: null,
  created_at: '2026-10-24T02:00:00Z',
  updated_at: '2026-10-24T02:00:00Z',
  ...changes,
});
export const bindingFixture = (changes: Partial<Binding> = {}): Binding => ({
  id: 'binding-1',
  community_id: 'community-1',
  house_id: 'house-1',
  claim_application_id: 'claim-1',
  house_label_snapshot: '梧桐里一期 · 3栋1单元1202室',
  status: 'active',
  effective_enabled: true,
  granted_at: '2026-10-10T00:00:00Z',
  ended_at: null,
  end_reason: null,
  row_version: 1,
  created_at: '2026-10-10T00:00:00Z',
  updated_at: '2026-10-10T00:00:00Z',
  ...changes,
});
export const entryFixture = (
  changes: Partial<SettlementEntry> = {},
): SettlementEntry => ({
  id: 'entry-1',
  bill_id: 'bill-1',
  entry_type: 'receipt',
  source_type: 'offline',
  amount_cents: 1000,
  received_on: '2026-10-05',
  display_type: 'offline_receipt',
  own_payment_order_id: null,
  created_at: '2026-10-05T02:00:00Z',
  ...changes,
});
export const pageFixture = <T>(
  items: T[],
  total = items.length,
  page = 1,
  pageSize = 20,
): PageResult<T> => ({ items, total, page, page_size: pageSize });

type Definition = Record<string, unknown> & { data: Record<string, unknown> };
type Instance = Definition & { setData(values: Record<string, unknown>): void };
export function pageHarness(definition: Definition) {
  const instance = {
    ...definition,
    data: structuredClone(definition.data),
  } as Instance;
  instance.setData = (values) => Object.assign(instance.data, values);
  return {
    data: instance.data,
    set(name: string, value: unknown) {
      instance[name] = value;
    },
    invoke<T = void>(method: string, ...args: unknown[]): T {
      return (instance[method] as (...values: unknown[]) => T).apply(
        instance,
        args,
      );
    },
  };
}
