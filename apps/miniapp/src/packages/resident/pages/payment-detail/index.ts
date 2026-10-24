import { order } from '../../../../core/api';
import { formatTime, money } from '../../../../core/format';
import {
  canContinuePayment,
  PaymentController,
  reconcilePaymentOrder,
} from '../../../../core/payments';
import { ApiError, errorText } from '../../../../core/request';
import { onSessionReset, requireSession } from '../../../../core/session';
import { PaymentOrder } from '../../../../core/types';
import { go, pageUrl } from '../../../../ui/navigation';
import {
  panelMessage,
  paymentPresentation,
  rememberPanelMessage,
} from './view';

Page({
  data: {
    loading: true,
    busy: false,
    error: '',
    message: '',
    item: null as PaymentOrder | null,
    title: '',
    description: '',
    icon: 'clock-3',
    tone: '',
    amount: '',
    created: '',
    paid: '',
    summary: '',
    months: '',
    posted: false,
    closed: false,
    canPay: false,
    canRefresh: false,
    canClose: false,
    closeSheet: false,
  },
  id: '',
  epoch: 0,
  visible: false,
  pollCount: 0,
  timer: null as ReturnType<typeof setTimeout> | null,
  off: () => {},
  controller: null as PaymentController | null,
  onLoad(options) {
    this.id = options.id || '';
    this.controller = new PaymentController();
    this.off = onSessionReset(() => {
      this.epoch++;
      this.stopPolling();
      this.setData({
        item: null,
        busy: false,
        loading: false,
        error: '登录状态已更新，请重新登录后继续。',
        message: '',
        closeSheet: false,
      });
    });
  },
  onShow() {
    this.visible = true;
    this.pollCount = 0;
    void this.load();
  },
  async onPullDownRefresh() {
    if (this.data.busy) {
      wx.stopPullDownRefresh();
      return;
    }
    this.pollCount = 0;
    try {
      await this.load();
    } finally {
      wx.stopPullDownRefresh();
    }
  },
  onHide() {
    this.visible = false;
    this.epoch++;
    this.stopPolling();
    this.controller?.pause();
    this.setData({ busy: false, loading: false, closeSheet: false });
  },
  onUnload() {
    this.visible = false;
    this.epoch++;
    this.stopPolling();
    this.controller?.dispose();
    this.off();
  },
  stopPolling() {
    if (this.timer !== null) clearTimeout(this.timer);
    this.timer = null;
  },
  schedulePolling() {
    this.stopPolling();
    if (
      !this.visible ||
      this.data.busy ||
      this.pollCount >= 24 ||
      !this.data.item ||
      this.data.posted ||
      this.data.closed
    )
      return;
    this.timer = setTimeout(() => {
      this.timer = null;
      this.pollCount++;
      void this.load(true);
    }, 2500);
  },
  show(item: PaymentOrder, message = panelMessage(item.id)) {
    reconcilePaymentOrder(item);
    const presentation = paymentPresentation(item, message);
    this.setData({
      item,
      ...presentation,
      message: presentation.posted || presentation.closed ? '' : message,
      amount: money(item.amount_cents),
      created: formatTime(item.created_at),
      paid: formatTime(item.paid_at),
      summary: item.items.map((part) => part.house_label_snapshot).join('；'),
      months: item.items
        .map((part) => part.billing_month.slice(0, 7).replace('-', '年') + '月')
        .join('、'),
    });
  },
  async load(background = false) {
    if (
      !this.visible ||
      this.data.busy ||
      !requireSession(pageUrl('payment-detail', { id: this.id }))
    )
      return;
    this.stopPolling();
    const epoch = ++this.epoch;
    if (!background) this.setData({ loading: true, error: '' });
    try {
      const item = await order(this.id);
      if (epoch !== this.epoch || !this.visible) return;
      this.show(item);
      this.setData({ error: '' });
    } catch (error) {
      if (epoch === this.epoch && this.visible)
        this.setData({
          error: errorText(error),
          ...(error instanceof ApiError &&
          [401, 403, 404].includes(error.status)
            ? { item: null, canPay: false, canClose: false, canRefresh: false }
            : {}),
        });
    } finally {
      if (epoch === this.epoch && this.visible) {
        this.setData({ loading: false });
        this.schedulePolling();
      }
    }
  },
  retry() {
    this.pollCount = 0;
    void this.load();
  },
  async pay() {
    if (!this.data.item || !canContinuePayment(this.data.item)) return;
    await this.perform('pay');
  },
  async verify() {
    await this.perform('refresh');
  },
  openClose() {
    if (this.data.canClose && !this.data.busy)
      this.setData({ closeSheet: true });
  },
  closeSheet() {
    if (!this.data.busy) this.setData({ closeSheet: false });
  },
  async confirmClose() {
    await this.perform('close');
  },
  async perform(action: 'pay' | 'refresh' | 'close') {
    const item = this.data.item;
    const controller = this.controller;
    if (
      !item ||
      !controller ||
      this.data.busy ||
      this.data.loading ||
      !this.visible
    )
      return;
    if (
      (action === 'pay' && !canContinuePayment(item)) ||
      (action === 'refresh' && !this.data.canRefresh) ||
      (action === 'close' && !this.data.canClose)
    )
      return;
    this.stopPolling();
    const epoch = ++this.epoch;
    this.setData({
      busy: true,
      error: '',
      message: '正在核实原订单，请勿重复付款。',
    });
    try {
      if (action === 'pay') {
        const result = await controller.pay(item);
        if (epoch !== this.epoch || !this.visible) return;
        rememberPanelMessage(result.order.id, result.message);
        this.show(result.order, result.message);
      } else {
        const result = await (action === 'close'
          ? controller.close(item)
          : controller.refresh(item));
        if (epoch !== this.epoch || !this.visible) return;
        this.show(result);
      }
      this.setData({ closeSheet: false });
    } catch (error) {
      if (epoch === this.epoch && this.visible) {
        if (!(
          error instanceof ApiError && [401, 403, 404].includes(error.status)
        ))
          this.show(item, '结果确认中，请勿重复付款。');
        this.setData({
          ...(error instanceof ApiError &&
          [401, 403, 404].includes(error.status)
            ? { item: null, canPay: false, canRefresh: false, canClose: false }
            : {}),
          error: errorText(error),
          message: '结果确认中，请勿重复付款；请核实原订单。',
          closeSheet: false,
        });
      }
    } finally {
      if (epoch === this.epoch && this.visible) {
        this.setData({ busy: false });
        this.pollCount = 0;
        this.schedulePolling();
      }
    }
  },
  backToBill() {
    if (!this.data.busy && this.data.closed && this.data.item?.items[0])
      go('bill-detail', { id: this.data.item.items[0].bill_id });
  },
  records() {
    if (!this.data.busy) go('payment-orders');
  },
});
