import { beforeEach, expect, it, vi } from 'vitest';
import type { ResidentBill } from '../../../src/packages/resident/billing/types';
import type { PaymentOrder } from '../../../src/packages/resident/payments/types';
const api = vi.hoisted(() => ({
  order: vi.fn(),
  createOrder: vi.fn(),
  parameters: vi.fn(),
  refresh: vi.fn(),
}));
const auth = vi.hoisted(() => ({
  owner: 'resident-a',
  reset: [] as (() => void)[],
}));
const panel = vi.hoisted(() => vi.fn());
vi.mock('../../../src/packages/resident/payments/api', () => api);
vi.mock('../../../src/shared/wechat/payment', () => ({
  requestPayment: panel,
}));
vi.mock('../../../src/auth/resident', () => ({
  currentCredential: () => (auth.owner ? { userId: auth.owner } : null),
  onSessionReset: (callback: () => void) => {
    auth.reset.push(callback);
    return () => {};
  },
}));
const storage = new Map<string, unknown>();
const bill = {
  id: 'bill',
  row_version: 1,
  own_payment_order_id: null,
} as ResidentBill;
const payable = {
  id: 'payment',
  status: 'payable',
  confirmation_status: 'unconfirmed',
  available_actions: ['continue_payment', 'refresh', 'close'],
} as PaymentOrder;
beforeEach(() => {
  vi.resetModules();
  vi.clearAllMocks();
  storage.clear();
  auth.owner = 'resident-a';
  auth.reset = [];
  vi.stubGlobal('wx', {
    getStorageSync: (key: string) => storage.get(key),
    setStorageSync: (key: string, value: unknown) =>
      storage.set(key, structuredClone(value)),
    removeStorageSync: (key: string) => storage.delete(key),
    getStorageInfoSync: () => ({ keys: [...storage.keys()] }),
  });
});
it('reopens an unknown creation with the original key and exact original input', async () => {
  const { PaymentController } =
    await import('../../../src/packages/resident/payments/controller');
  const { ApiError } = await import('../../../src/shared/http/client');
  api.createOrder
    .mockRejectedValueOnce(new ApiError(0, 'network', '网络错误'))
    .mockResolvedValueOnce(payable);
  api.order.mockResolvedValue(payable);
  const first = new PaymentController();
  await expect(first.create(bill)).rejects.toThrow();
  first.dispose();
  const reopened = new PaymentController();
  await reopened.create({ ...bill, row_version: 9 });
  expect(api.createOrder.mock.calls[1]).toEqual(api.createOrder.mock.calls[0]);
  expect(api.createOrder.mock.calls[1][0]).toEqual({
    items: [{ bill_id: 'bill', expected_row_version: 1 }],
  });
});
it.each(['success', 'cancelled', 'unknown'])(
  'treats panel %s as a reason to verify the same server order',
  async (result) => {
    const { PaymentController } =
      await import('../../../src/packages/resident/payments/controller');
    const current = {
      ...payable,
      available_actions: ['refresh'],
      status: 'unknown',
    };
    api.order.mockResolvedValueOnce(payable).mockResolvedValueOnce(current);
    api.parameters.mockResolvedValue({
      client_parameters: {
        paySign: 'memory-only',
        package: 'prepay_id=private',
      },
    });
    api.refresh.mockResolvedValue(current);
    panel.mockResolvedValue(result);
    const observed = await new PaymentController().pay(payable);
    expect(observed.order.status).toBe('unknown');
    expect(api.refresh).toHaveBeenCalledWith('payment');
    expect(api.createOrder).not.toHaveBeenCalled();
    expect(JSON.stringify([...storage])).not.toContain('memory-only');
  },
);
it('does not request parameters for trusted collection awaiting posting', async () => {
  const { PaymentController } =
    await import('../../../src/packages/resident/payments/controller');
  const current = {
    ...payable,
    confirmation_status: 'awaiting_posting',
    available_actions: ['refresh'],
  };
  api.order.mockResolvedValue(current);
  expect((await new PaymentController().pay(payable)).order).toEqual(current);
  expect(api.parameters).not.toHaveBeenCalled();
  expect(panel).not.toHaveBeenCalled();
});
it('removes the old resident draft and rejects a late response after session reset', async () => {
  const { PaymentController } =
    await import('../../../src/packages/resident/payments/controller');
  let finish!: (value: PaymentOrder) => void;
  api.createOrder.mockImplementation(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  const controller = new PaymentController();
  const pending = controller.create(bill);
  expect(storage.size).toBe(1);
  auth.owner = 'resident-b';
  auth.reset.forEach((callback) => callback());
  finish(payable);
  await expect(pending).rejects.toThrow();
  expect(storage.size).toBe(0);
  expect(api.order).not.toHaveBeenCalled();
});
it('does not erase a newer unknown request when an older closed order is displayed', async () => {
  const { pending, rememberOrder, clearPending } =
    await import('../../../src/packages/resident/payments/pending');
  const value = pending('bill', 2);
  rememberOrder('bill', value, 'new-payment');
  clearPending('bill', 'old-closed-payment');
  expect(pending('bill', 3)).toEqual({ ...value, orderId: 'new-payment' });
});
it('retains the original request after hiding and rejects its late result', async () => {
  const { PaymentController } =
    await import('../../../src/packages/resident/payments/controller');
  let finish!: (value: PaymentOrder) => void;
  api.createOrder
    .mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    )
    .mockResolvedValueOnce(payable);
  api.order.mockResolvedValue(payable);
  const controller = new PaymentController();
  const first = controller.create(bill);
  controller.pause();
  finish(payable);
  await expect(first).rejects.toThrow();
  expect(api.order).not.toHaveBeenCalled();
  await controller.create({ ...bill, row_version: 2 });
  expect(api.createOrder.mock.calls[1]).toEqual(api.createOrder.mock.calls[0]);
});
it('does not invoke the payment panel when parameters arrive after hiding', async () => {
  const { PaymentController } =
    await import('../../../src/packages/resident/payments/controller');
  let finish!: (value: unknown) => void;
  api.order.mockResolvedValue(payable);
  api.parameters.mockImplementation(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  const controller = new PaymentController();
  const payment = controller.pay(payable);
  await vi.waitFor(() => expect(api.parameters).toHaveBeenCalledOnce());
  controller.pause();
  finish({ client_parameters: { paySign: 'memory-only' } });
  await expect(payment).rejects.toThrow();
  expect(panel).not.toHaveBeenCalled();
});
