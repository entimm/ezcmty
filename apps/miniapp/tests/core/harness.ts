import { vi } from 'vitest';
import { API_BASE_URL } from '../../src/config';
import { PaymentOrder, ResidentBill } from '../../src/packages/resident/types';

export function device(userId = 'resident-a') {
  const storage = new Map<string, unknown>([
    [
      'ezcmty:' + API_BASE_URL + ':client-session',
      {
        token: 'test-token',
        userId,
        expiresAt: '2030-01-01T00:00:00Z',
      },
    ],
  ]);
  const wx = {
    getStorageSync: vi.fn((key: string) => storage.get(key)),
    setStorageSync: vi.fn((key: string, value: unknown) => {
      storage.set(key, value);
    }),
    removeStorageSync: vi.fn((key: string) => {
      storage.delete(key);
    }),
    getStorageInfoSync: vi.fn(() => ({ keys: [...storage.keys()] })),
    navigateTo: vi.fn(),
    reLaunch: vi.fn(),
    request: vi
      .fn()
      .mockImplementation(
        (options: {
          url: string;
          success(value: unknown): void;
          complete(): void;
        }) => {
          if (options.url.endsWith('/client-sessions/current')) {
            options.success({
              statusCode: 200,
              data: {
                expires_at: '2030-01-01T00:00:00Z',
                user: { id: userId, enabled: true },
              },
              header: {},
            });
            options.complete();
          }
          return { abort: vi.fn() };
        },
      ),
    login: vi.fn(),
    requestPayment: vi.fn(),
  };
  vi.stubGlobal('wx', wx);
  return { wx, storage };
}

export function bill(overrides: Partial<ResidentBill> = {}): ResidentBill {
  return {
    id: 'bill-a',
    property_company_id: 'property-a',
    property_company_name: '美好物业',
    community_id: 'community-a',
    house_id: 'house-a',
    house_label_snapshot: '梧桐里 3 栋 1 单元 1202',
    bill_type: 'property_fee',
    billing_month: '2026-10',
    period_start: '2026-10-01',
    period_end: '2026-10-31',
    receivable_cents: 20000,
    settled_cents: 0,
    outstanding_cents: 20000,
    lifecycle_status: 'active',
    settlement_status: 'unpaid',
    due_date: null,
    is_overdue: false,
    row_version: 3,
    payment_availability: 'available',
    own_payment_order_id: null,
    created_at: '2026-10-01T00:00:00Z',
    updated_at: '2026-10-01T00:00:00Z',
    ...overrides,
  };
}

export function order(overrides: Partial<PaymentOrder> = {}): PaymentOrder {
  return {
    id: 'order-a',
    order_no: 'test-order-a',
    merchant_name: '美好物业',
    amount_cents: 20000,
    payer_total_cents: null,
    status: 'payable',
    confirmation_status: 'unconfirmed',
    available_actions: ['continue_payment', 'refresh', 'close'],
    items: [
      {
        id: 'item-a',
        bill_id: 'bill-a',
        bill_type: 'property_fee',
        billing_month: '2026-10',
        house_label_snapshot: '梧桐里 3 栋 1 单元 1202',
        amount_cents: 20000,
      },
    ],
    expires_at: '2030-01-01T00:00:00Z',
    paid_at: null,
    closed_at: null,
    created_at: '2026-10-01T00:00:00Z',
    updated_at: '2026-10-01T00:00:00Z',
    ...overrides,
  };
}
