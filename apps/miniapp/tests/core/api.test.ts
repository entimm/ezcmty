import { afterEach, beforeEach, expect, it, vi } from 'vitest';

beforeEach(() => vi.resetModules());
afterEach(() => vi.doUnmock('../../src/core/session'));

it('queries current authorized bills separately from payer-only historical order recovery', async () => {
  const residentRequest = vi.fn().mockResolvedValue({ items: [] });
  vi.doMock('../../src/core/session', () => ({ residentRequest }));
  const api = await import('../../src/core/api');
  await api.bills('binding/a', 2, 'all', {
    billing_month_from: '2025-01',
    billing_month_to: '2026-10',
  });
  await api.orders(1, '', {
    idempotency_key: 'mini_original_key',
    confirmation_status: 'unconfirmed',
  });
  expect(residentRequest.mock.calls[0][0]).toBe(
    '/miniapp-users/me/house-bindings/binding%2Fa/bills?page=2&scope=all&billing_month_from=2025-01&billing_month_to=2026-10',
  );
  expect(residentRequest.mock.calls[1][0]).toBe(
    '/miniapp-users/me/payment-orders?page=1&idempotency_key=mini_original_key&confirmation_status=unconfirmed',
  );
});

it('submits only the permitted bill and version with the original key', async () => {
  const residentRequest = vi.fn().mockResolvedValue({});
  vi.doMock('../../src/core/session', () => ({ residentRequest }));
  const api = await import('../../src/core/api');
  await api.createOrder(
    { items: [{ bill_id: 'bill-a', expected_row_version: 4 }] },
    'mini_original_key',
  );
  expect(residentRequest).toHaveBeenCalledWith(
    '/miniapp-users/me/payment-orders',
    {
      method: 'POST',
      key: 'mini_original_key',
      data: { items: [{ bill_id: 'bill-a', expected_row_version: 4 }] },
    },
  );
});
