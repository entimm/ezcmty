import { onSessionReset, requireSession } from '../../../../auth/resident';
import { errorText } from '../../../../shared/http/client';
import { bill } from '../../billing/api';
import { availability, money } from '../../billing/presentation';
import { ResidentBill } from '../../billing/types';
import { PaymentController } from '../../payments/controller';
import { paymentUrl } from '../../payments/presentation';
Page({
  data: {
    loading: false,
    error: '',
    busy: false,
    item: null as ResidentBill | null,
    amount: '',
    hint: '',
    canPay: false,
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
      this.setData({ item: null, busy: false, loading: false, error: '' });
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
    void this.load();
  },
  show(item: ResidentBill) {
    this.setData({
      item,
      amount: money(item.outstanding_cents),
      hint: availability[item.payment_availability],
      canPay: ['available', 'own_payment_in_progress'].includes(
        item.payment_availability,
      ),
    });
  },
  async load() {
    if (
      !requireSession(
        '/packages/resident/pages/payment-confirm/index?id=' + this.id,
      )
    )
      return;
    const epoch = ++this.epoch;
    this.setData({ loading: true, error: '' });
    try {
      const item = await bill(this.id);
      if (epoch === this.epoch) this.show(item);
    } catch (error) {
      if (epoch === this.epoch)
        this.setData({ error: errorText(error), item: null });
    } finally {
      if (epoch === this.epoch) this.setData({ loading: false });
    }
  },
  async submit() {
    const item = this.data.item;
    if (
      !item ||
      !this.data.canPay ||
      this.data.busy ||
      this.data.loading ||
      !this.controller
    )
      return;
    const epoch = this.epoch;
    this.setData({ busy: true, error: '' });
    try {
      const fresh = await bill(item.id);
      if (epoch !== this.epoch) return;
      if (
        fresh.row_version !== item.row_version ||
        fresh.outstanding_cents !== item.outstanding_cents
      ) {
        this.show(fresh);
        this.setData({ error: '账单金额或状态已变化，请重新核对后确认' });
        return;
      }
      if (
        !['available', 'own_payment_in_progress'].includes(
          fresh.payment_availability,
        )
      ) {
        this.show(fresh);
        return;
      }
      const order = await this.controller.create(fresh);
      if (epoch !== this.epoch) return;
      wx.redirectTo({ url: paymentUrl(order.id) });
    } catch (error) {
      if (epoch === this.epoch)
        this.setData({
          error: errorText(error) + '；请核实原支付，勿重复付款。',
        });
    } finally {
      if (epoch === this.epoch) this.setData({ busy: false });
    }
  },
});
