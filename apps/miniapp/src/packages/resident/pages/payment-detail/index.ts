import { onSessionReset, requireSession } from '../../../../auth/resident';
import { errorText } from '../../../../shared/http/client';
import { confirm, formatTime } from '../../../../shared/wechat/ui';
import { money } from '../../billing/presentation';
import * as api from '../../payments/api';
import { PaymentController } from '../../payments/controller';
import { clearPending } from '../../payments/pending';
import { paymentLabel } from '../../payments/presentation';
import { PaymentOrder } from '../../payments/types';
Page({
  data: {
    loading: false,
    busy: false,
    error: '',
    message: '',
    item: null as PaymentOrder | null,
    amount: '',
    label: '',
    paid: '',
    canPay: false,
    canRefresh: false,
    canClose: false,
  },
  id: '',
  epoch: 0,
  off: () => {},
  controller: null as PaymentController | null,
  onLoad(options) {
    this.id = options.id || '';
    this.controller = new PaymentController();
    this.off = onSessionReset(() => {
      this.epoch++;
      this.setData({ item: null, busy: false, loading: false, message: '' });
    });
  },
  onUnload() {
    this.off();
    this.controller?.dispose();
    this.epoch++;
  },
  onHide() {
    this.epoch++;
    this.controller?.pause();
    this.setData({ busy: false, loading: false });
  },
  onShow() {
    if (!this.data.busy) void this.load();
  },
  show(item: PaymentOrder) {
    this.setData({
      item,
      amount: money(item.amount_cents),
      label: paymentLabel(item),
      paid: formatTime(item.paid_at),
      canPay: item.available_actions.includes('continue_payment'),
      canRefresh: item.available_actions.includes('refresh'),
      canClose: item.available_actions.includes('close'),
    });
    if (item.status === 'closed' || item.status === 'succeeded')
      item.items.forEach((bill) => clearPending(bill.bill_id, item.id));
  },
  async load() {
    if (
      !requireSession(
        '/packages/resident/pages/payment-detail/index?id=' + this.id,
      )
    )
      return;
    const epoch = ++this.epoch;
    this.setData({ loading: true, error: '' });
    try {
      const item = await api.order(this.id);
      if (epoch === this.epoch) this.show(item);
    } catch (error) {
      if (epoch === this.epoch)
        this.setData({ error: errorText(error), item: null });
    } finally {
      if (epoch === this.epoch) this.setData({ loading: false });
    }
  },
  async act(event: WechatMiniprogram.TouchEvent) {
    const action: string = event.currentTarget.dataset.action;
    const item = this.data.item;
    if (!item || this.data.busy || this.data.loading || !this.controller)
      return;
    if (
      (action === 'pay' && !this.data.canPay) ||
      (action === 'refresh' && !this.data.canRefresh) ||
      (action === 'close' && !this.data.canClose)
    )
      return;
    const epoch = this.epoch;
    if (
      action === 'close' &&
      (!(await confirm(
        '核实并关闭原订单',
        '关闭前仍须核实原支付结果；已收款将继续确认缴费。',
      )) ||
        epoch !== this.epoch)
    )
      return;
    this.setData({
      busy: true,
      error: '',
      message: '正在核实原订单，请勿重复付款',
    });
    try {
      if (action === 'pay') {
        const result = await this.controller.pay(item);
        if (epoch === this.epoch) {
          this.show(result.order);
          this.setData({ message: result.message });
        }
      } else {
        if (action === 'close') await api.close(item.id);
        else await api.refresh(item.id);
        if (epoch !== this.epoch) return;
        const current = await api.order(item.id);
        if (epoch === this.epoch) this.show(current);
      }
    } catch (error) {
      if (epoch === this.epoch)
        this.setData({
          error: errorText(error),
          message: '结果确认中，请勿重复付款；请重新读取原订单。',
        });
    } finally {
      if (epoch === this.epoch) this.setData({ busy: false });
    }
  },
  backToBill() {
    const item = this.data.item;
    if (item?.status === 'closed')
      wx.navigateTo({
        url:
          '/packages/resident/pages/bill-detail/index?id=' +
          item.items[0].bill_id,
      });
  },
});
