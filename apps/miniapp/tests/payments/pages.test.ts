import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { PaymentOrder } from '../../src/core/types';
import {
  billFixture,
  bindingFixture,
  entryFixture,
  orderFixture,
  pageFixture,
  pageHarness,
} from './fixtures';

const mocks = vi.hoisted(() => ({
  bill: vi.fn(),
  bills: vi.fn(),
  bindings: vi.fn(),
  entries: vi.fn(),
  orders: vi.fn(),
  order: vi.fn(),
  recover: vi.fn(),
  create: vi.fn(),
  pay: vi.fn(),
  refresh: vi.fn(),
  close: vi.fn(),
  pause: vi.fn(),
  dispose: vi.fn(),
  canContinue: vi.fn(),
  uncertain: vi.fn(),
  go: vi.fn(),
  requireSession: vi.fn(),
  credential: vi.fn(),
  sessionListeners: [] as (() => void)[],
  setSelection: vi.fn(),
}));
vi.mock('../../src/core/api', () => ({
  bill: mocks.bill,
  bills: mocks.bills,
  bindings: mocks.bindings,
  entries: mocks.entries,
  orders: mocks.orders,
  order: mocks.order,
}));
vi.mock('../../src/core/session', () => ({
  requireSession: mocks.requireSession,
  onSessionReset: (listener: () => void) => {
    mocks.sessionListeners.push(listener);
    return () => {
      const index = mocks.sessionListeners.indexOf(listener);
      if (index >= 0) mocks.sessionListeners.splice(index, 1);
    };
  },
  currentCredential: mocks.credential,
}));
vi.mock('../../src/core/selection', () => ({
  getSelectedBindingId: () => 'binding-1',
  setSelectedBindingId: mocks.setSelection,
}));
vi.mock('../../src/core/payments', () => ({
  reconcilePaymentOrder: (item: PaymentOrder) => item,
  canContinuePayment: mocks.canContinue,
  hasUncertainPayment: mocks.uncertain,
  PaymentController: class {
    recover = mocks.recover;
    create = mocks.create;
    pay = mocks.pay;
    refresh = mocks.refresh;
    close = mocks.close;
    pause = mocks.pause;
    dispose = mocks.dispose;
  },
}));
vi.mock('../../src/ui/navigation', () => ({
  go: mocks.go,
  pageUrl: (key: string) => key,
}));

let captured: Parameters<typeof pageHarness>[0];
beforeEach(() => {
  vi.resetModules();
  vi.resetAllMocks();
  vi.useFakeTimers();
  vi.stubGlobal('Page', (definition: typeof captured) => {
    captured = definition;
  });
  vi.stubGlobal('wx', { stopPullDownRefresh: vi.fn() });
  mocks.sessionListeners.length = 0;
  mocks.credential.mockReturnValue({ userId: 'resident-1' });
  mocks.requireSession.mockReturnValue(true);
  mocks.canContinue.mockImplementation((item: PaymentOrder) =>
    item.available_actions.includes('continue_payment'),
  );
  mocks.uncertain.mockReturnValue(false);
  mocks.recover.mockResolvedValue(null);
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('支付状态展示', () => {
  it('只有服务端成功且入账才显示缴费成功', async () => {
    const { paymentPresentation } =
      await import('../../src/packages/resident/pages/payment-detail/view');
    expect(
      paymentPresentation(
        orderFixture({
          status: 'succeeded',
          confirmation_status: 'posted',
          available_actions: [],
        }),
      ).title,
    ).toBe('缴费成功');
    expect(
      paymentPresentation(
        orderFixture({
          status: 'succeeded',
          confirmation_status: 'unconfirmed',
          available_actions: [],
        }),
      ).posted,
    ).toBe(false);
  });
  it('已收款待入账禁止继续付款与关闭', async () => {
    const { paymentPresentation } =
      await import('../../src/packages/resident/pages/payment-detail/view');
    const result = paymentPresentation(
      orderFixture({ confirmation_status: 'awaiting_posting' }),
    );
    expect(result.title).toBe('已收款，正在确认缴费');
    expect(result.canPay).toBe(false);
    expect(result.canClose).toBe(false);
  });
  it('本机支付结果未知时保持原单确认状态', async () => {
    mocks.canContinue.mockReturnValue(false);
    mocks.uncertain.mockReturnValue(true);
    const { paymentPresentation } =
      await import('../../src/packages/resident/pages/payment-detail/view');
    const result = paymentPresentation(orderFixture({ status: 'pending' }));
    expect(result.title).toBe('正在确认支付结果');
    expect(result.canPay).toBe(false);
  });
});

describe('支付确认', () => {
  it('提交前发现授权结束时清除旧账单，保留原单恢复入口', async () => {
    await import('../../src/packages/resident/pages/payment-confirm/index');
    const { ApiError } = await import('../../src/core/request');
    const page = pageHarness(captured);
    page.invoke('onLoad', { id: 'bill-1' });
    page.set('visible', true);
    mocks.bill.mockResolvedValueOnce(billFixture());
    await page.invoke<Promise<void>>('load');
    mocks.bill.mockRejectedValueOnce(
      new ApiError(404, 'resource.not_found', '授权已结束'),
    );
    await page.invoke<Promise<void>>('submit');
    expect(page.data.item).toBeNull();
    expect(page.data.canPay).toBe(false);
    expect(page.data.needsRecovery).toBe(true);
    expect(mocks.create).not.toHaveBeenCalled();
  });
  it.each(['payment-confirm', 'payment-detail'])(
    '支付忙碌时 %s 下拉不打断写操作',
    async (key) => {
      await import(`../../src/packages/resident/pages/${key}/index.ts`);
      const page = pageHarness(captured);
      page.invoke('onLoad', { id: 'bill-or-order-1' });
      page.set('visible', true);
      page.data.busy = true;
      await page.invoke<Promise<void>>('onPullDownRefresh');
      expect(page.data.busy).toBe(true);
      expect(mocks.bill).not.toHaveBeenCalled();
      expect(mocks.order).not.toHaveBeenCalled();
      expect(wx.stopPullDownRefresh).toHaveBeenCalledOnce();
    },
  );

  it('连续点击确认只恢复和处理一次原支付', async () => {
    await import('../../src/packages/resident/pages/payment-confirm/index');
    const page = pageHarness(captured);
    page.invoke('onLoad', { id: 'bill-1' });
    page.set('visible', true);
    mocks.bill.mockResolvedValue(billFixture());
    await page.invoke<Promise<void>>('load');
    let finish!: (item: PaymentOrder) => void;
    mocks.recover.mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    const submitting = page.invoke<Promise<void>>('submit');
    await page.invoke<Promise<void>>('submit');
    finish(orderFixture());
    await submitting;
    expect(mocks.recover).toHaveBeenCalledTimes(1);
    expect(mocks.go).toHaveBeenCalledTimes(1);
    expect(mocks.create).not.toHaveBeenCalled();
  });

  it('金额或版本变化后重新显示金额，等待再次确认', async () => {
    await import('../../src/packages/resident/pages/payment-confirm/index');
    const page = pageHarness(captured);
    page.invoke('onLoad', { id: 'bill-1' });
    page.set('visible', true);
    mocks.bill.mockResolvedValueOnce(billFixture());
    await page.invoke<Promise<void>>('load');
    mocks.bill.mockResolvedValueOnce(
      billFixture({
        row_version: 5,
        outstanding_cents: 18000,
        settled_cents: 2000,
      }),
    );
    await page.invoke<Promise<void>>('submit');
    expect(page.data.amount).toBe('180.00');
    expect(page.data.error).toContain('重新核对');
    expect(mocks.create).not.toHaveBeenCalled();
    expect(mocks.pay).not.toHaveBeenCalled();
  });
  it('当前房屋访问失效后仍可恢复本人原订单', async () => {
    await import('../../src/packages/resident/pages/payment-confirm/index');
    const page = pageHarness(captured);
    page.invoke('onLoad', { id: 'bill-1' });
    page.set('visible', true);
    mocks.bill.mockRejectedValue(new Error('房屋授权已结束'));
    await page.invoke<Promise<void>>('load');
    mocks.recover.mockResolvedValue(
      orderFixture({
        status: 'unknown',
        available_actions: ['refresh', 'close'],
      }),
    );
    await page.invoke<Promise<void>>('recover');
    expect(mocks.go).toHaveBeenCalledWith('payment-detail', { id: 'order-1' });
    expect(mocks.create).not.toHaveBeenCalled();
    expect(mocks.pay).not.toHaveBeenCalled();
  });
  it('支付取消后转回原订单详情，不以面板结果判定成功', async () => {
    await import('../../src/packages/resident/pages/payment-confirm/index');
    const page = pageHarness(captured);
    page.invoke('onLoad', { id: 'bill-1' });
    page.set('visible', true);
    mocks.bill.mockResolvedValue(billFixture());
    mocks.create.mockResolvedValue(orderFixture());
    mocks.pay.mockResolvedValue({
      order: orderFixture(),
      message: '已取消本次支付面板，原订单保留',
    });
    await page.invoke<Promise<void>>('load');
    await page.invoke<Promise<void>>('submit');
    expect(mocks.go).toHaveBeenLastCalledWith('payment-detail', {
      id: 'order-1',
    });
    expect(mocks.create).toHaveBeenCalledTimes(1);
    expect(mocks.pay).toHaveBeenCalledTimes(1);
  });
});

describe('账单与收款流水', () => {
  it('账单选房卡分层显示小区和房号，切换后仍按原绑定请求', async () => {
    await import('../../src/packages/resident/pages/bills/index');
    const page = pageHarness(captured);
    page.invoke('onLoad', {});
    page.set('visible', true);
    const first = bindingFixture({
      house_label_snapshot: '梧桐里／一期／3栋／1单元／1202室',
    });
    const second = bindingFixture({
      id: 'binding-2',
      house_id: 'house-2',
      house_label_snapshot: '云栖花园／2栋／602室',
    });
    mocks.bindings.mockResolvedValue(pageFixture([first, second]));
    mocks.bills.mockResolvedValue(pageFixture([]));
    await page.invoke<Promise<void>>('load');
    expect(page.data.selected).toMatchObject({
      id: first.id,
      community: '梧桐里',
      room: '一期 · 3栋 · 1单元 · 1202室',
    });
    await page.invoke<Promise<void>>('confirmHouse', {
      detail: { binding: second },
    });
    expect(page.data.selected).toMatchObject({
      id: second.id,
      community: '云栖花园',
      room: '2栋 · 602室',
    });
    expect(mocks.bills.mock.calls.map((call) => call[0])).toEqual([
      'binding-1',
      'binding-2',
    ]);
  });

  it('游客进入缴费主页不请求账务，不自动跳登录，保留登录入口', async () => {
    mocks.credential.mockReturnValue(null);
    await import('../../src/packages/resident/pages/bills/index');
    const page = pageHarness(captured);
    page.invoke('onLoad', {});
    page.set('visible', true);
    await page.invoke<Promise<void>>('load');
    expect(page.data.signed).toBe(false);
    expect(page.data.loading).toBe(false);
    expect(page.data.items).toEqual([]);
    expect(mocks.bindings).not.toHaveBeenCalled();
    expect(mocks.bills).not.toHaveBeenCalled();
    expect(mocks.requireSession).not.toHaveBeenCalled();
    expect(mocks.go).not.toHaveBeenCalled();
    page.invoke('login');
    expect(mocks.go).toHaveBeenCalledWith('login', { return_to: 'bills' });
  });
  it('缴费主页会话失效后清账务并留在页内登录门禁', async () => {
    await import('../../src/packages/resident/pages/bills/index');
    const page = pageHarness(captured);
    page.invoke('onLoad', {});
    page.set('visible', true);
    mocks.bindings.mockResolvedValue(pageFixture([bindingFixture()]));
    mocks.bills.mockResolvedValue(pageFixture([billFixture()]));
    await page.invoke<Promise<void>>('load');
    expect(page.data.signed).toBe(true);
    mocks.credential.mockReturnValue(null);
    mocks.sessionListeners.forEach((listener) => listener());
    expect(page.data.signed).toBe(false);
    expect(page.data.items).toEqual([]);
    expect(page.data.selected).toBeNull();
    expect(page.data.houses).toEqual([]);
    expect(page.data.error).toBe('');
    expect(mocks.go).not.toHaveBeenCalled();
    await page.invoke<Promise<void>>('load');
    expect(mocks.bindings).toHaveBeenCalledTimes(1);
    expect(mocks.bills).toHaveBeenCalledTimes(1);
  });

  it('分页时房屋授权结束，停止显示该房屋账务', async () => {
    await import('../../src/packages/resident/pages/bills/index');
    const { ApiError } = await import('../../src/core/request');
    const page = pageHarness(captured);
    page.invoke('onLoad', {});
    page.set('visible', true);
    mocks.bindings.mockResolvedValue(pageFixture([bindingFixture()]));
    mocks.bills.mockResolvedValueOnce(pageFixture([billFixture()], 2, 1, 1));
    await page.invoke<Promise<void>>('load');
    mocks.bills.mockRejectedValueOnce(
      new ApiError(404, 'resident.house_not_found', '房屋授权已结束'),
    );
    await page.invoke<Promise<void>>('more');
    expect(page.data.items).toEqual([]);
    expect(page.data.hasMore).toBe(false);
    expect(page.data.error).toBeTruthy();
  });

  it('账单加载更多失败保留已显示账单与分页位置', async () => {
    await import('../../src/packages/resident/pages/bills/index');
    const page = pageHarness(captured);
    page.invoke('onLoad', {});
    page.set('visible', true);
    mocks.bindings.mockResolvedValue(pageFixture([bindingFixture()]));
    mocks.bills.mockResolvedValueOnce(pageFixture([billFixture()], 2, 1, 1));
    await page.invoke<Promise<void>>('load');
    mocks.bills.mockRejectedValueOnce(new Error('网络中断'));
    await page.invoke<Promise<void>>('more');
    expect(page.data.items).toHaveLength(1);
    expect(page.data.page).toBe(1);
    expect(page.data.moreError).toBeTruthy();
  });
  it('他人线上流水不提供本人订单跳转', async () => {
    await import('../../src/packages/resident/pages/bill-detail/index');
    const page = pageHarness(captured);
    page.invoke('onLoad', { id: 'bill-1' });
    page.set('visible', true);
    mocks.bill.mockResolvedValue(billFixture());
    mocks.entries.mockResolvedValue(
      pageFixture([
        entryFixture({
          display_type: 'other_payment',
          source_type: 'online_payment',
          own_payment_order_id: 'must-not-link',
        }),
      ]),
    );
    await page.invoke<Promise<void>>('load');
    const entries = page.data.entries as {
      id: string;
      orderId: string | null;
    }[];
    expect(entries[0].orderId).toBeNull();
    page.invoke('openOrder', { currentTarget: { dataset: { id: 'entry-1' } } });
    expect(mocks.go).not.toHaveBeenCalled();
  });
  it('页面隐藏后旧收款流水不会回填', async () => {
    await import('../../src/packages/resident/pages/bill-detail/index');
    const page = pageHarness(captured);
    page.invoke('onLoad', { id: 'bill-1' });
    page.set('visible', true);
    let resolveEntries!: (value: ReturnType<typeof pageFixture>) => void;
    mocks.bill.mockResolvedValue(billFixture());
    mocks.entries.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveEntries = resolve;
        }),
    );
    const loading = page.invoke<Promise<void>>('load');
    await vi.waitFor(() => expect(mocks.entries).toHaveBeenCalled());
    page.invoke('onHide');
    resolveEntries(pageFixture([entryFixture()]));
    await loading;
    expect(page.data.entries).toEqual([]);
    expect(page.data.entryLoading).toBe(false);
  });
});

describe('本人缴费记录与原单操作', () => {
  it('待确认按统一顺序扫描，跨过已完成页并包含所有非终态', async () => {
    await import('../../src/packages/resident/pages/payment-orders/index');
    const page = pageHarness(captured);
    page.invoke('onLoad');
    page.set('visible', true);
    page.data.filter = 'pending';
    mocks.orders
      .mockResolvedValueOnce(
        pageFixture(
          [
            orderFixture({
              id: 'paid',
              status: 'succeeded',
              confirmation_status: 'posted',
              available_actions: [],
            }),
            orderFixture({
              id: 'closed',
              status: 'closed',
              available_actions: [],
            }),
          ],
          6,
          1,
          2,
        ),
      )
      .mockResolvedValueOnce(
        pageFixture(
          [
            orderFixture({ id: 'pending', status: 'pending' }),
            orderFixture({ id: 'unknown', status: 'unknown' }),
          ],
          6,
          2,
          2,
        ),
      )
      .mockResolvedValueOnce(
        pageFixture(
          [
            orderFixture({ id: 'payable', status: 'payable' }),
            orderFixture({ id: 'closing', status: 'closing' }),
          ],
          6,
          3,
          2,
        ),
      );
    await page.invoke<Promise<void>>('load');
    expect(page.data.page).toBe(2);
    expect(page.data.hasMore).toBe(true);
    await page.invoke<Promise<void>>('load', true);
    expect(page.data.items).toHaveLength(4);
    expect(mocks.orders.mock.calls.map((call) => call.slice(0, 2))).toEqual([
      [1, ''],
      [2, ''],
      [3, ''],
    ]);
    expect(page.data.total).toBe(4);
    expect(page.data.hasMore).toBe(false);
    expect(mocks.bindings).not.toHaveBeenCalled();
    expect(mocks.bill).not.toHaveBeenCalled();
  });
  it('稀疏历史扫描未结束时不误报没有待确认记录', async () => {
    await import('../../src/packages/resident/pages/payment-orders/index');
    const page = pageHarness(captured);
    page.invoke('onLoad');
    page.set('visible', true);
    page.data.filter = 'pending';
    mocks.orders.mockImplementation(async (page: number) =>
      pageFixture(
        [
          orderFixture({
            id: String(page),
            status: 'succeeded',
            confirmation_status: 'posted',
            available_actions: [],
          }),
        ],
        20,
        page,
        1,
      ),
    );
    await page.invoke<Promise<void>>('load');
    expect(page.data.items).toEqual([]);
    expect(page.data.page).toBe(5);
    expect(page.data.hasMore).toBe(true);
    expect(page.data.scanned).toBe(5);
  });
  it('待确认扫描中途失败保留原列表和来源页，重试不跳页', async () => {
    await import('../../src/packages/resident/pages/payment-orders/index');
    const page = pageHarness(captured);
    page.invoke('onLoad');
    page.set('visible', true);
    page.data.filter = 'pending';
    mocks.orders.mockResolvedValueOnce(
      pageFixture([orderFixture({ id: 'first', status: 'unknown' })], 3, 1, 1),
    );
    await page.invoke<Promise<void>>('load');
    mocks.orders
      .mockResolvedValueOnce(
        pageFixture(
          [
            orderFixture({
              id: 'done',
              status: 'closed',
              available_actions: [],
            }),
          ],
          3,
          2,
          1,
        ),
      )
      .mockRejectedValueOnce(new Error('网络中断'));
    await page.invoke<Promise<void>>('load', true);
    expect(page.data.items).toHaveLength(1);
    expect(page.data.page).toBe(1);
    mocks.orders
      .mockResolvedValueOnce(
        pageFixture(
          [
            orderFixture({
              id: 'done',
              status: 'closed',
              available_actions: [],
            }),
          ],
          3,
          2,
          1,
        ),
      )
      .mockResolvedValueOnce(
        pageFixture([orderFixture({ id: 'last', status: 'pending' })], 3, 3, 1),
      );
    await page.invoke<Promise<void>>('load', true);
    expect(page.data.items).toHaveLength(2);
    expect(page.data.page).toBe(3);
    expect(mocks.orders.mock.calls.map((call) => call[0])).toEqual([
      1, 2, 3, 2, 3,
    ]);
  });
  it('关单结果未知后不再恢复旧的继续支付动作', async () => {
    await import('../../src/packages/resident/pages/payment-detail/index');
    const page = pageHarness(captured);
    page.invoke('onLoad', { id: 'order-1' });
    page.set('visible', true);
    mocks.order.mockResolvedValue(orderFixture());
    await page.invoke<Promise<void>>('load');
    mocks.close.mockImplementation(async () => {
      mocks.canContinue.mockReturnValue(false);
      mocks.uncertain.mockReturnValue(true);
      throw new Error('网络中断');
    });
    await page.invoke<Promise<void>>('confirmClose');
    expect(page.data.canPay).toBe(false);
    expect(page.data.title).toBe('正在确认支付结果');
    await page.invoke<Promise<void>>('pay');
    expect(mocks.pay).not.toHaveBeenCalled();
  });
  it('原单操作发现无权限后清除旧详情和动作', async () => {
    await import('../../src/packages/resident/pages/payment-detail/index');
    const { ApiError } = await import('../../src/core/request');
    const page = pageHarness(captured);
    page.invoke('onLoad', { id: 'order-1' });
    page.set('visible', true);
    mocks.order.mockResolvedValue(orderFixture());
    await page.invoke<Promise<void>>('load');
    mocks.refresh.mockRejectedValueOnce(
      new ApiError(403, 'resident.disabled', '账号不可用'),
    );
    await page.invoke<Promise<void>>('verify');
    expect(page.data.item).toBeNull();
    expect(page.data.canPay).toBe(false);
    expect(page.data.canRefresh).toBe(false);
    expect(page.data.canClose).toBe(false);
  });
  it('未知订单的继续付款入口不会调用支付', async () => {
    mocks.canContinue.mockReturnValue(false);
    await import('../../src/packages/resident/pages/payment-detail/index');
    const page = pageHarness(captured);
    page.invoke('onLoad', { id: 'order-1' });
    page.set('visible', true);
    mocks.order.mockResolvedValue(
      orderFixture({
        status: 'unknown',
        available_actions: ['refresh', 'close'],
      }),
    );
    await page.invoke<Promise<void>>('load');
    await page.invoke<Promise<void>>('pay');
    expect(page.data.canPay).toBe(false);
    expect(mocks.pay).not.toHaveBeenCalled();
    expect(mocks.bindings).not.toHaveBeenCalled();
  });
  it('关单先等待底部确认，异步受理不展示成功', async () => {
    await import('../../src/packages/resident/pages/payment-detail/index');
    const page = pageHarness(captured);
    page.invoke('onLoad', { id: 'order-1' });
    page.set('visible', true);
    mocks.order.mockResolvedValue(orderFixture());
    mocks.close.mockResolvedValue(
      orderFixture({ status: 'closing', available_actions: ['refresh'] }),
    );
    await page.invoke<Promise<void>>('load');
    page.invoke('openClose');
    expect(page.data.closeSheet).toBe(true);
    expect(mocks.close).not.toHaveBeenCalled();
    await page.invoke<Promise<void>>('confirmClose');
    expect(page.data.title).toBe('正在核实并关闭原订单');
    expect(page.data.posted).toBe(false);
    expect(page.data.canPay).toBe(false);
  });
});
