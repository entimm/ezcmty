import { requireIdentity } from '../../../../core/identities';
import { onContextReset } from '../../../../core/identities';
import { bill } from '../../api';
import { money } from '../../../../core/format';
import { canContinuePayment, PaymentController } from '../../payments';
import { ApiError, errorText } from '../../../../core/request';
import { PaymentOrder, ResidentBill } from '../../types';
import { go, pageUrl } from '../../../../ui/navigation';
import { billPresentation, rememberPanelMessage } from '../payment-detail/view';

Page({
  data: {
    loading: true,
    busy: false,
    error: '',
    item: null as ResidentBill | null,
    month: '',
    amount: '',
    receivable: '',
    settled: '',
    hint: '',
    canPay: false,
    needsRecovery: false,
  },
  id: '',
  epoch: 0,
  visible: false,
  off: () => {},
  controller: null as PaymentController | null,
  onLoad(options) {
    this.id = options.id || '';
    this.controller = new PaymentController();
    this.off = onContextReset(() => {
      this.epoch++;
      this.setData({
        item: null,
        busy: false,
        loading: false,
        error: '登录状态已更新，请重新登录后继续。',
        needsRecovery: false,
      });
    });
  },
  onShow() {
    this.visible = true;
    void this.load();
  },
  async onPullDownRefresh() {
    if (this.data.busy) {
      wx.stopPullDownRefresh();
      return;
    }
    try {
      await this.load();
    } finally {
      wx.stopPullDownRefresh();
    }
  },
  onHide() {
    this.visible = false;
    this.epoch++;
    this.controller?.pause();
    this.setData({ busy: false, loading: false });
  },
  onUnload() {
    this.visible = false;
    this.epoch++;
    this.controller?.dispose();
    this.off();
  },
  showBill(item: ResidentBill) {
    const presentation = billPresentation(item);
    this.setData({
      item,
      month: item.billing_month.slice(0, 7).replace('-', '年') + '月',
      amount: money(item.outstanding_cents),
      receivable: money(item.receivable_cents),
      settled: money(item.settled_cents),
      canPay: presentation.canPay,
      hint: presentation.hint,
    });
  },
  async load() {
    if (this.data.busy) return;
    if (
      !requireIdentity('resident', pageUrl('payment-confirm', { id: this.id }))
    )
      return;
    const epoch = ++this.epoch;
    this.setData({ loading: true, error: '', needsRecovery: false });
    try {
      const item = await bill(this.id);
      if (epoch === this.epoch && this.visible) this.showBill(item);
    } catch (error) {
      if (epoch === this.epoch && this.visible)
        this.setData({
          item: null,
          error: errorText(error),
          needsRecovery: true,
        });
    } finally {
      if (epoch === this.epoch && this.visible)
        this.setData({ loading: false });
    }
  },
  async submit() {
    const item = this.data.item;
    const controller = this.controller;
    if (
      !item ||
      !controller ||
      !this.data.canPay ||
      this.data.busy ||
      this.data.loading
    )
      return;
    const epoch = this.epoch;
    this.setData({ busy: true, error: '' });
    let knownOrder: PaymentOrder | null = null;
    try {
      // A retained request is resolved before reading current house data. It may
      // already have created a personal order even if house access later ended.
      const recovered = await controller.recover(this.id);
      if (epoch !== this.epoch || !this.visible) return;
      if (recovered) {
        go('payment-detail', { id: recovered.id });
        return;
      }
      const fresh = await bill(this.id);
      if (epoch !== this.epoch || !this.visible) return;
      if (
        fresh.row_version !== item.row_version ||
        fresh.outstanding_cents !== item.outstanding_cents
      ) {
        this.showBill(fresh);
        this.setData({ error: '账单金额或状态已变化，请重新核对后确认。' });
        return;
      }
      this.showBill(fresh);
      if (!billPresentation(fresh).canPay) return;
      knownOrder = await controller.create(fresh);
      if (epoch !== this.epoch || !this.visible) return;
      if (canContinuePayment(knownOrder)) {
        const result = await controller.pay(knownOrder);
        if (epoch !== this.epoch || !this.visible) return;
        knownOrder = result.order;
        rememberPanelMessage(result.order.id, result.message);
      }
      go('payment-detail', { id: knownOrder.id });
    } catch (error) {
      if (epoch !== this.epoch || !this.visible) return;
      if (knownOrder) {
        go('payment-detail', { id: knownOrder.id });
        return;
      }
      this.setData({
        error: errorText(error) || '结果尚未确认，请恢复原支付结果。',
        needsRecovery: true,
        ...(error instanceof ApiError && [401, 403, 404].includes(error.status)
          ? { item: null, canPay: false }
          : {}),
      });
    } finally {
      if (epoch === this.epoch && this.visible) this.setData({ busy: false });
    }
  },
  async recover() {
    if (!this.controller || this.data.busy || this.data.loading) return;
    const epoch = this.epoch;
    this.setData({ busy: true, error: '' });
    try {
      const item = await this.controller.recover(this.id);
      if (epoch !== this.epoch || !this.visible) return;
      if (item) go('payment-detail', { id: item.id });
      else
        this.setData({
          error:
            '暂未找到可恢复的原订单。请查看本人缴费记录，或重新读取账单核对。',
          needsRecovery: true,
        });
    } catch (error) {
      if (epoch === this.epoch && this.visible)
        this.setData({
          error: errorText(error),
          needsRecovery: true,
          ...(error instanceof ApiError &&
          [401, 403, 404].includes(error.status)
            ? { item: null, canPay: false }
            : {}),
        });
    } finally {
      if (epoch === this.epoch && this.visible) this.setData({ busy: false });
    }
  },
  backToBill() {
    if (!this.data.busy) go('bill-detail', { id: this.id });
  },
  records() {
    if (!this.data.busy) go('payment-orders');
  },
});
