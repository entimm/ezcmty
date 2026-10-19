import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import type { PaymentOrder } from '../../../src/packages/resident/payments/types';

const api = vi.hoisted(() => ({
  order: vi.fn(),
  refresh: vi.fn(),
  close: vi.fn(),
}));
const controller = vi.hoisted(() => ({
  pay: vi.fn(),
  pause: vi.fn(),
  dispose: vi.fn(),
}));
const auth = vi.hoisted(() => ({ reset: () => {} }));
const clearPending = vi.hoisted(() => vi.fn());
vi.mock('../../../src/packages/resident/payments/api', () => api);
vi.mock('../../../src/packages/resident/payments/controller', () => ({
  PaymentController: class {
    pay = controller.pay;
    pause = controller.pause;
    dispose = controller.dispose;
  },
}));
vi.mock('../../../src/packages/resident/payments/pending', () => ({
  clearPending,
}));
vi.mock('../../../src/auth/resident', () => ({
  requireSession: () => true,
  onSessionReset: (callback: () => void) => {
    auth.reset = callback;
    return () => {};
  },
}));

interface DetailPage {
  data: {
    item: PaymentOrder | null;
    busy: boolean;
    loading: boolean;
    error: string;
    message: string;
    label: string;
    canPay: boolean;
  };
  setData: (value: object) => void;
  onLoad: (options: Record<string, string>) => void;
  onShow: () => void;
  onHide: () => void;
  onUnload: () => void;
  act: (event: WechatMiniprogram.TouchEvent) => Promise<void>;
}

const preparing: PaymentOrder = {
  id: 'payment',
  order_no: 'py_original',
  merchant_name: '物业',
  amount_cents: 10,
  payer_total_cents: null,
  status: 'pending',
  confirmation_status: 'unconfirmed',
  available_actions: ['refresh', 'close'],
  items: [
    {
      id: 'item',
      bill_id: 'bill',
      bill_type: 'property_fee',
      billing_month: '2026-10',
      house_label_snapshot: '1栋101',
      amount_cents: 10,
    },
  ],
  expires_at: '2026-10-19T10:15:00Z',
  paid_at: null,
  closed_at: null,
  created_at: '2026-10-19T10:00:00Z',
  updated_at: '2026-10-19T10:00:00Z',
};
const payable: PaymentOrder = {
  ...preparing,
  status: 'payable',
  available_actions: ['continue_payment', 'refresh', 'close'],
};
const posted: PaymentOrder = {
  ...preparing,
  status: 'succeeded',
  confirmation_status: 'posted',
  available_actions: [],
  paid_at: '2026-10-19T10:01:00Z',
};
const action = (name: string) =>
  ({
    currentTarget: { dataset: { action: name } },
  }) as unknown as WechatMiniprogram.TouchEvent;

let page: DetailPage;
beforeEach(async () => {
  vi.useFakeTimers();
  vi.resetModules();
  vi.resetAllMocks();
  api.order.mockResolvedValue(preparing);
  vi.stubGlobal('wx', {
    showModal: vi.fn((options) => options.success({ confirm: false })),
  });
  vi.stubGlobal('Page', (definition: DetailPage) => {
    page = definition;
    page.data = structuredClone(definition.data);
    page.setData = (value: object) => Object.assign(page.data, value);
  });
  await import('../../../src/packages/resident/pages/payment-detail/index');
  page.onLoad({ id: preparing.id });
});
afterEach(() => {
  page.onUnload();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

async function open() {
  page.onShow();
  await vi.advanceTimersByTimeAsync(0);
}

it('updates a newly created order when prepayment becomes ready without invoking payment', async () => {
  api.order.mockResolvedValueOnce(preparing).mockResolvedValue(payable);
  await open();
  expect(page.data.canPay).toBe(false);
  expect(page.data.label).toBe('正在准备支付，请稍候');
  await vi.advanceTimersByTimeAsync(2000);
  expect(page.data.item?.id).toBe(preparing.id);
  expect(page.data.canPay).toBe(true);
  expect(page.data.label).toBe('待支付，可继续原订单');
  expect(page.data.loading).toBe(false);
  expect(api.refresh).not.toHaveBeenCalled();
  expect(controller.pay).not.toHaveBeenCalled();
});

it('continues reading the original order after payment and clears the interim message once posted', async () => {
  api.order.mockResolvedValueOnce(payable).mockResolvedValue(posted);
  controller.pay.mockResolvedValue({
    order: payable,
    message: '正在确认缴费结果，请勿重复付款',
  });
  await open();
  await page.act(action('pay'));
  expect(page.data.message).toContain('正在确认');
  await vi.advanceTimersByTimeAsync(2000);
  expect(page.data.label).toBe('缴费成功');
  expect(page.data.message).toBe('');
  expect(clearPending).toHaveBeenCalledWith('bill', 'payment');
  expect(controller.pay).toHaveBeenCalledExactlyOnceWith(payable);
  expect(vi.getTimerCount()).toBe(0);
});

it('shows a posted result immediately when the payment action already observes it', async () => {
  api.order.mockResolvedValue(payable);
  controller.pay.mockResolvedValue({
    order: posted,
    message: '正在确认缴费结果，请勿重复付款',
  });
  await open();
  await page.act(action('pay'));
  expect(page.data.label).toBe('缴费成功');
  expect(page.data.message).toBe('');
  expect(vi.getTimerCount()).toBe(0);
});

it.each(['hide', 'unload', 'reset'])(
  'stops polling and discards an in-flight response after %s',
  async (event) => {
    let finish!: (order: PaymentOrder) => void;
    api.order.mockResolvedValueOnce(preparing).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    await open();
    await vi.advanceTimersByTimeAsync(2000);
    if (event === 'hide') page.onHide();
    else if (event === 'unload') page.onUnload();
    else auth.reset();
    finish(payable);
    await vi.advanceTimersByTimeAsync(60_000);
    expect(api.order).toHaveBeenCalledTimes(2);
    expect(page.data.canPay).toBe(false);
    expect(vi.getTimerCount()).toBe(0);
    if (event === 'reset') expect(page.data.item).toBeNull();
  },
);

it('keeps a manual confirmation result when an older automatic read arrives late', async () => {
  let finish!: (order: PaymentOrder) => void;
  api.order
    .mockResolvedValueOnce(preparing)
    .mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    )
    .mockResolvedValueOnce(posted);
  await open();
  await vi.advanceTimersByTimeAsync(2000);
  await page.act(action('refresh'));
  finish(preparing);
  await vi.advanceTimersByTimeAsync(60_000);
  expect(page.data.item?.status).toBe('succeeded');
  expect(page.data.label).toBe('缴费成功');
  expect(api.refresh).toHaveBeenCalledExactlyOnceWith('payment');
  expect(api.order).toHaveBeenCalledTimes(3);
  expect(vi.getTimerCount()).toBe(0);
});

it('keeps the original order through a temporary read failure and recovers on the next read', async () => {
  api.order
    .mockResolvedValueOnce(preparing)
    .mockRejectedValueOnce(new Error('offline'))
    .mockResolvedValueOnce(payable);
  await open();
  await vi.advanceTimersByTimeAsync(2000);
  expect(page.data.item).toEqual(preparing);
  expect(page.data.error).not.toBe('');
  await vi.advanceTimersByTimeAsync(2000);
  expect(page.data.canPay).toBe(true);
  expect(page.data.error).toBe('');
});

it('bounds automatic reads and allows the user to resume verification on the same order', async () => {
  await open();
  await vi.advanceTimersByTimeAsync(120_000);
  expect(api.order).toHaveBeenCalledTimes(31);
  expect(vi.getTimerCount()).toBe(0);
  await vi.advanceTimersByTimeAsync(60_000);
  expect(api.order).toHaveBeenCalledTimes(31);
  await page.act(action('refresh'));
  await vi.advanceTimersByTimeAsync(2000);
  expect(api.order).toHaveBeenCalledTimes(33);
  expect(api.refresh).toHaveBeenCalledExactlyOnceWith('payment');
});

it('stops reading when the original order is confirmed closed', async () => {
  api.order.mockResolvedValueOnce(preparing).mockResolvedValueOnce({
    ...preparing,
    status: 'closed',
    available_actions: [],
  });
  await open();
  await vi.advanceTimersByTimeAsync(2000);
  expect(page.data.label).toBe('支付已确认关闭');
  expect(clearPending).toHaveBeenCalledWith('bill', 'payment');
  expect(vi.getTimerCount()).toBe(0);
});

it('resumes automatic reads when the user cancels the closure confirmation', async () => {
  await open();
  await page.act(action('close'));
  expect(api.close).not.toHaveBeenCalled();
  await vi.advanceTimersByTimeAsync(2000);
  expect(api.order).toHaveBeenCalledTimes(2);
});
