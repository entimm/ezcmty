import { beforeEach, expect, it, vi } from 'vitest';
import type { ResidentBill } from '../../../src/packages/resident/billing/types';
const api = vi.hoisted(() => ({ bill: vi.fn() }));
const controller = vi.hoisted(() => ({ create: vi.fn(), dispose: vi.fn() }));
const auth = vi.hoisted(() => ({ reset: () => {} }));
vi.mock('../../../src/packages/resident/billing/api', () => api);
vi.mock('../../../src/packages/resident/payments/controller', () => ({
  PaymentController: class {
    create = controller.create;
    dispose = controller.dispose;
  },
}));
vi.mock('../../../src/auth/resident', () => ({
  requireSession: () => true,
  onSessionReset: (callback: () => void) => {
    auth.reset = callback;
    return () => {};
  },
}));
interface ConfirmationPage {
  data: {
    item: ResidentBill | null;
    canPay: boolean;
    busy: boolean;
    loading: boolean;
    error: string;
    amount: string;
  };
  setData: (value: object) => void;
  onLoad: (options: Record<string, string>) => void;
  submit: () => Promise<void>;
}
const original = {
  id: 'bill',
  row_version: 1,
  outstanding_cents: 10000,
  payment_availability: 'available',
  own_payment_order_id: null,
} as ResidentBill;
let page: ConfirmationPage;
beforeEach(async () => {
  vi.resetModules();
  vi.clearAllMocks();
  vi.stubGlobal('wx', { redirectTo: vi.fn() });
  vi.stubGlobal('Page', (definition: ConfirmationPage) => {
    page = definition;
    page.data = structuredClone(definition.data);
    page.setData = (value: object) => Object.assign(page.data, value);
  });
  await import('../../../src/packages/resident/pages/payment-confirm/index');
  page.onLoad({ id: original.id });
  Object.assign(page.data, { item: original, canPay: true });
});
it('requires a new confirmation when a refreshed amount changes', async () => {
  api.bill.mockResolvedValue({
    ...original,
    row_version: 2,
    outstanding_cents: 12000,
  });
  await page.submit();
  expect(page.data.amount).toBe('120.00');
  expect(page.data.error).toContain('重新核对');
  expect(controller.create).not.toHaveBeenCalled();
  expect(page.data.busy).toBe(false);
});
it('prevents double-clicks from starting a second creation while the first is in flight', async () => {
  let finish!: (value: object) => void;
  api.bill.mockResolvedValue(original);
  controller.create.mockImplementation(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  const first = page.submit();
  await Promise.resolve();
  await page.submit();
  expect(controller.create).toHaveBeenCalledTimes(1);
  finish({ id: 'original-payment' });
  await first;
  expect(wx.redirectTo).toHaveBeenCalledWith({
    url: '/packages/resident/pages/payment-detail/index?id=original-payment',
  });
});
it('discards a late refresh after session reset and does not create a payment', async () => {
  let finish!: (value: ResidentBill) => void;
  api.bill.mockImplementation(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  const pending = page.submit();
  auth.reset();
  finish(original);
  await pending;
  expect(page.data.item).toBeNull();
  expect(page.data.busy).toBe(false);
  expect(controller.create).not.toHaveBeenCalled();
  expect(wx.redirectTo).not.toHaveBeenCalled();
});
