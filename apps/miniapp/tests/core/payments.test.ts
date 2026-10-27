import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { API_BASE_URL } from '../../src/config';
import { bill, device, order } from './harness';

function paymentApi() {
  return {
    bill: vi.fn().mockResolvedValue(bill()),
    orders: vi
      .fn()
      .mockResolvedValue({ items: [], total: 0, page: 1, page_size: 1 }),
    order: vi.fn().mockResolvedValue(order()),
    createOrder: vi.fn().mockResolvedValue(order()),
    parameters: vi.fn().mockResolvedValue({
      payment_order_id: 'order-a',
      channel: 'wechat_pay',
      client_parameters: {
        timeStamp: '123',
        nonceStr: 'test-nonce',
        package: 'prepay_id=secret-test-prepay',
        signType: 'RSA',
        paySign: 'secret-test-signature',
      },
    }),
    refresh: vi.fn().mockResolvedValue(order()),
    close: vi
      .fn()
      .mockResolvedValue(
        order({ status: 'closing', available_actions: ['refresh', 'close'] }),
      ),
  };
}

beforeEach(() => {
  vi.resetModules();
});
afterEach(() => {
  vi.doUnmock('../../src/packages/resident/api');
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

it('recovers an uncertain create using its original key and version after house authorization ends', async () => {
  device();
  const { ApiError } = await import('../../src/core/request');
  const api = paymentApi();
  api.createOrder.mockRejectedValueOnce(
    new ApiError(503, 'service.unavailable', '响应未知'),
  );
  vi.doMock('../../src/packages/resident/api', () => api);
  const { PaymentController } =
    await import('../../src/packages/resident/payments');
  const first = new PaymentController();
  await expect(first.create(bill())).rejects.toMatchObject({ status: 503 });
  first.dispose();
  api.bill.mockRejectedValue(
    new ApiError(404, 'resource.not_found', '房屋授权已结束'),
  );
  const reopened = new PaymentController();
  await expect(reopened.recover('bill-a')).resolves.toMatchObject({
    id: 'order-a',
  });
  expect(api.bill).toHaveBeenCalledOnce();
  expect(api.createOrder.mock.calls[0]).toEqual(api.createOrder.mock.calls[1]);
  expect(api.orders.mock.calls[0][2].idempotency_key).toBe(
    api.orders.mock.calls[1][2].idempotency_key,
  );
  reopened.dispose();
});

it('finds a submitted order by its exact idempotency key instead of creating it again', async () => {
  device();
  const { ApiError } = await import('../../src/core/request');
  const api = paymentApi();
  api.createOrder.mockRejectedValueOnce(new ApiError(0, 'network', '响应未知'));
  vi.doMock('../../src/packages/resident/api', () => api);
  const { PaymentController } =
    await import('../../src/packages/resident/payments');
  const controller = new PaymentController();
  await expect(controller.create(bill())).rejects.toMatchObject({ status: 0 });
  api.orders.mockResolvedValue({
    items: [order()],
    total: 1,
    page: 1,
    page_size: 1,
  });
  await expect(controller.recover('bill-a')).resolves.toMatchObject({
    id: 'order-a',
  });
  expect(api.createOrder).toHaveBeenCalledOnce();
  controller.dispose();
});

it('keeps the original key after an ambiguous conflict instead of silently rotating it', async () => {
  device();
  const { ApiError } = await import('../../src/core/request');
  const api = paymentApi();
  api.createOrder.mockRejectedValueOnce(
    new ApiError(409, 'payment.idempotency_conflict', '冲突'),
  );
  vi.doMock('../../src/packages/resident/api', () => api);
  const { PaymentController } =
    await import('../../src/packages/resident/payments');
  const controller = new PaymentController();
  await expect(controller.create(bill())).rejects.toMatchObject({
    status: 409,
  });
  await controller.recover('bill-a');
  expect(api.createOrder.mock.calls[0]).toEqual(api.createOrder.mock.calls[1]);
  controller.dispose();
});

it('returns to confirmation when the currently authorized bill amount changes', async () => {
  device();
  const api = paymentApi();
  api.bill.mockResolvedValue(
    bill({ row_version: 4, outstanding_cents: 25000 }),
  );
  vi.doMock('../../src/packages/resident/api', () => api);
  const { PaymentController } =
    await import('../../src/packages/resident/payments');
  const controller = new PaymentController();
  await expect(controller.create(bill())).rejects.toMatchObject({
    code: 'payment.bill_version_conflict',
  });
  expect(api.createOrder).not.toHaveBeenCalled();
  controller.dispose();
});

it('blocks repeated payment after an unknown SDK result even while an asynchronous refresh still says payable', async () => {
  const { wx, storage } = device();
  wx.requestPayment.mockImplementation(
    (options: { fail: (value: { errMsg: string }) => void }) =>
      options.fail({ errMsg: 'requestPayment:fail unknown' }),
  );
  const api = paymentApi();
  vi.doMock('../../src/packages/resident/api', () => api);
  const { PaymentController, canContinuePayment, hasUncertainPayment } =
    await import('../../src/packages/resident/payments');
  const controller = new PaymentController();
  const result = await controller.pay(order());
  expect(result.message).toBe('结果确认中，请勿重复付款');
  expect(hasUncertainPayment(result.order)).toBe(true);
  expect(canContinuePayment(result.order)).toBe(false);
  controller.dispose();
  const reopened = new PaymentController();
  await reopened.pay(order());
  expect(wx.requestPayment).toHaveBeenCalledOnce();
  expect(api.createOrder).not.toHaveBeenCalled();
  expect(JSON.stringify([...storage.values()])).not.toContain(
    'secret-test-signature',
  );
  expect(JSON.stringify([...storage.values()])).not.toContain(
    'secret-test-prepay',
  );
  reopened.dispose();
});

it('treats SDK success as unconfirmed until the backend confirms posting', async () => {
  const { wx } = device();
  wx.requestPayment.mockImplementation((options: { success: () => void }) =>
    options.success(),
  );
  const api = paymentApi();
  vi.doMock('../../src/packages/resident/api', () => api);
  const { PaymentController, canContinuePayment, hasUncertainPayment } =
    await import('../../src/packages/resident/payments');
  const controller = new PaymentController();
  const result = await controller.pay(order());
  expect(result.order.status).toBe('payable');
  expect(result.message).toContain('确认中');
  expect(canContinuePayment(result.order)).toBe(false);
  api.order.mockResolvedValue(
    order({
      status: 'succeeded',
      confirmation_status: 'posted',
      available_actions: [],
    }),
  );
  const posted = await controller.refresh(result.order);
  expect(posted.status).toBe('succeeded');
  expect(canContinuePayment(posted)).toBe(false);
  expect(hasUncertainPayment(posted)).toBe(false);
  controller.dispose();
});

it('retains the original order after panel cancellation and permits continuing only that order', async () => {
  const { wx } = device();
  wx.requestPayment.mockImplementation(
    (options: { fail: (value: { errMsg: string }) => void }) =>
      options.fail({ errMsg: 'requestPayment:fail cancel' }),
  );
  const api = paymentApi();
  vi.doMock('../../src/packages/resident/api', () => api);
  const { PaymentController, canContinuePayment } =
    await import('../../src/packages/resident/payments');
  const controller = new PaymentController();
  const result = await controller.pay(order());
  expect(result.message).toContain('原订单保留');
  expect(canContinuePayment(result.order)).toBe(true);
  expect(api.createOrder).not.toHaveBeenCalled();
  expect(api.refresh).toHaveBeenCalledWith('order-a');
  controller.dispose();
});

it('never signs another payment for confirmed receipts awaiting posting', async () => {
  device();
  const api = paymentApi();
  api.order.mockResolvedValue(
    order({ confirmation_status: 'awaiting_posting' }),
  );
  vi.doMock('../../src/packages/resident/api', () => api);
  const { PaymentController } =
    await import('../../src/packages/resident/payments');
  const controller = new PaymentController();
  await controller.pay(order());
  expect(api.parameters).not.toHaveBeenCalled();
  controller.dispose();
});

it.each(['success', 'cancelled'] as const)(
  'drops a late SDK %s after login as another user without changing their payment state',
  async (panel) => {
    const { wx, storage } = device();
    let complete!: () => void;
    let opened!: () => void;
    const ready = new Promise<void>((resolve) => {
      opened = resolve;
    });
    wx.requestPayment.mockImplementation(
      (options: {
        success: () => void;
        fail: (reason: { errMsg: string }) => void;
      }) => {
        complete =
          panel === 'success'
            ? options.success
            : () => options.fail({ errMsg: 'requestPayment:fail cancel' });
        opened();
      },
    );
    const api = paymentApi();
    vi.doMock('../../src/packages/resident/api', () => api);
    const { PaymentController } =
      await import('../../src/packages/resident/payments');
    const session = await import('../../src/core/session');
    const controller = new PaymentController();
    const pending = controller.pay(order());
    await ready;
    const userBKey =
      'ezcmty:' +
      API_BASE_URL +
      ':resident-payment:resident-b:uncertain:order-a';
    storage.set(userBKey, true);
    wx.login.mockImplementation(
      (options: { success: (result: { code: string }) => void }) => {
        options.success({ code: 'new-user-code' });
      },
    );
    wx.request.mockImplementation(
      (options: {
        success: (result: {
          statusCode: number;
          data: unknown;
          header: object;
        }) => void;
        complete: () => void;
      }) => {
        options.success({
          statusCode: 201,
          data: {
            token: 'token-b',
            expires_at: '2030-01-01T00:00:00Z',
            user: { id: 'resident-b', enabled: true },
          },
          header: {},
        });
        options.complete();
        return { abort: vi.fn() };
      },
    );
    await session.login();
    expect(session.currentCredential()?.userId).toBe('resident-b');
    const afterLogin = new Map(storage);
    complete();
    await expect(pending).rejects.toMatchObject({ name: 'StaleSessionError' });
    expect(api.refresh).not.toHaveBeenCalled();
    expect(
      [...storage.keys()].some((key) =>
        key.includes(':resident-payment:resident-a:'),
      ),
    ).toBe(true);
    expect(storage).toEqual(afterLogin);
    expect(storage.get(userBKey)).toBe(true);
    expect(session.currentCredential()?.userId).toBe('resident-b');
    controller.dispose();
  },
);

it('does not start a write when it cannot persist the original recovery key', async () => {
  const { wx } = device();
  wx.setStorageSync.mockImplementation(() => {
    throw new Error('storage full');
  });
  const api = paymentApi();
  vi.doMock('../../src/packages/resident/api', () => api);
  const { PaymentController } =
    await import('../../src/packages/resident/payments');
  const controller = new PaymentController();
  await expect(controller.create(bill())).rejects.toMatchObject({
    code: 'storage.unavailable',
  });
  expect(api.createOrder).not.toHaveBeenCalled();
  controller.dispose();
});

it('clears the original recovery record as soon as a directly read terminal order is observed', async () => {
  device();
  const api = paymentApi();
  vi.doMock('../../src/packages/resident/api', () => api);
  const { PaymentController, reconcilePaymentOrder } =
    await import('../../src/packages/resident/payments');
  const controller = new PaymentController();
  await controller.create(bill());
  reconcilePaymentOrder(order({ status: 'closed', available_actions: [] }));
  await expect(controller.recover('bill-a')).resolves.toBeNull();
  controller.dispose();
});

it('requires fresh confirmation after recovery proves that the original request was never created against the old bill version', async () => {
  device();
  const { ApiError } = await import('../../src/core/request');
  const api = paymentApi();
  api.createOrder.mockRejectedValueOnce(new ApiError(0, 'network', '响应未知'));
  vi.doMock('../../src/packages/resident/api', () => api);
  const { PaymentController } =
    await import('../../src/packages/resident/payments');
  const controller = new PaymentController();
  await expect(controller.create(bill())).rejects.toMatchObject({ status: 0 });
  api.createOrder.mockRejectedValueOnce(
    new ApiError(409, 'payment.bill_version_conflict', '账单版本已变化'),
  );
  await expect(controller.recover('bill-a')).rejects.toMatchObject({
    code: 'payment.bill_version_conflict',
  });
  await expect(controller.recover('bill-a')).resolves.toBeNull();
  controller.dispose();
});

it('persists an uncertain close before the POST so reopening cannot pay the original order again', async () => {
  device();
  const { ApiError } = await import('../../src/core/request');
  const api = paymentApi();
  api.close.mockRejectedValueOnce(
    new ApiError(503, 'service.unavailable', '关闭结果未知'),
  );
  vi.doMock('../../src/packages/resident/api', () => api);
  const { PaymentController, canContinuePayment, hasUncertainPayment } =
    await import('../../src/packages/resident/payments');
  const controller = new PaymentController();
  await expect(controller.close(order())).rejects.toMatchObject({
    status: 503,
  });
  controller.dispose();
  expect(hasUncertainPayment(order())).toBe(true);
  expect(canContinuePayment(order())).toBe(false);
  const reopened = new PaymentController();
  await reopened.pay(order());
  expect(api.parameters).not.toHaveBeenCalled();
  const stillPayable = await reopened.refresh(order());
  expect(canContinuePayment(stillPayable)).toBe(false);
  api.order.mockResolvedValue(
    order({ status: 'closed', available_actions: [] }),
  );
  const closed = await reopened.refresh(order());
  expect(hasUncertainPayment(closed)).toBe(false);
  reopened.dispose();
});
it('keeps the original unknown payment through 401 and fresh same-user login', async () => {
  const { wx, storage } = device();
  const api = paymentApi();
  vi.doMock('../../src/packages/resident/api', () => api);
  const { ApiError } = await import('../../src/core/request');
  api.createOrder.mockRejectedValueOnce(new ApiError(0, 'network', '响应未知'));
  const { PaymentController } =
    await import('../../src/packages/resident/payments');
  const session = await import('../../src/core/session');
  const first = new PaymentController();
  await expect(first.create(bill())).rejects.toMatchObject({ status: 0 });
  const original = api.createOrder.mock.calls[0];
  const key =
    'ezcmty:' + API_BASE_URL + ':resident-payment:resident-a:bill:bill-a';
  const saved = storage.get(key);
  wx.request.mockImplementation((call) => {
    const login = call.url.endsWith('/client-sessions');
    call.success({
      statusCode: login ? 201 : 401,
      data: login
        ? {
            token: 'fresh-token',
            user: { id: 'resident-a', enabled: true },
            expires_at: '2030-01-01T00:00:00Z',
          }
        : { code: 'auth.unauthenticated' },
      header: {},
    });
    call.complete();
    return { abort: vi.fn() };
  });
  await expect(
    session.clientRequest('/miniapp-users/me'),
  ).rejects.toMatchObject({ status: 401 });
  expect(storage.get(key)).toEqual(saved);
  wx.login.mockImplementation(
    (call: { success(result: { code: string }): void }) =>
      call.success({ code: 'fresh-code' }),
  );
  await session.login();
  const reopened = new PaymentController();
  await reopened.recover('bill-a');
  expect(api.createOrder.mock.calls[1]).toEqual(original);
  first.dispose();
  reopened.dispose();
});
