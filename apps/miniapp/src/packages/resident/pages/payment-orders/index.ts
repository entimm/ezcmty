import { onSessionReset, requireSession } from '../../../../auth/resident';
import { errorText } from '../../../../shared/http/client';
import { money } from '../../billing/presentation';
import { orders } from '../../payments/api';
import { paymentLabel, paymentUrl } from '../../payments/presentation';
import { PaymentOrder } from '../../payments/types';
interface Row extends PaymentOrder {
  label: string;
  amount: string;
}
Page({
  data: {
    loading: false,
    error: '',
    items: [] as Row[],
    total: 0,
    page: 1,
    status: '',
  },
  epoch: 0,
  off: () => {},
  onLoad() {
    this.off = onSessionReset(() => {
      this.epoch++;
      this.setData({ items: [], total: 0, loading: false });
    });
  },
  onUnload() {
    this.off();
    this.epoch++;
  },
  onShow() {
    void this.load();
  },
  async load(more = false) {
    if (!requireSession('/packages/resident/pages/payment-orders/index'))
      return;
    const epoch = ++this.epoch;
    this.setData({ loading: true, error: '' });
    try {
      const page = more ? this.data.page + 1 : 1;
      const result = await orders(page, this.data.status);
      if (epoch !== this.epoch) return;
      const items = result.items.map((item) => ({
        ...item,
        label: paymentLabel(item),
        amount: money(item.amount_cents),
      }));
      this.setData({
        items: more ? [...this.data.items, ...items] : items,
        total: result.total,
        page,
      });
    } catch (error) {
      if (epoch === this.epoch) this.setData({ error: errorText(error) });
    } finally {
      if (epoch === this.epoch) this.setData({ loading: false });
    }
  },
  filter(event: WechatMiniprogram.TouchEvent) {
    this.setData({
      status: event.currentTarget.dataset.status || '',
      items: [],
      total: 0,
    });
    void this.load();
  },
  more() {
    if (!this.data.loading) void this.load(true);
  },
  retry() {
    void this.load();
  },
  open(event: WechatMiniprogram.TouchEvent) {
    wx.navigateTo({ url: paymentUrl(event.currentTarget.dataset.id) });
  },
});
