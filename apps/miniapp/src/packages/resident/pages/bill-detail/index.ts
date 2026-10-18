import { onSessionReset, requireSession } from '../../../../auth/resident';
import { errorText } from '../../../../shared/http/client';
import { bill, entries } from '../../billing/api';
import { availability, entryLabels, money } from '../../billing/presentation';
import { ResidentBill } from '../../billing/types';
import { paymentUrl } from '../../payments/presentation';
interface Entry {
  id: string;
  label: string;
  amount: string;
  received: string;
}
Page({
  data: {
    loading: false,
    error: '',
    item: null as ResidentBill | null,
    amount: '',
    settled: '',
    outstanding: '',
    hint: '',
    canPay: false,
    entries: [] as Entry[],
    entryPage: 1,
    entryTotal: 0,
    entryError: '',
    entryLoading: false,
  },
  id: '',
  epoch: 0,
  off: () => {},
  onLoad(options) {
    this.id = options.id || '';
    this.off = onSessionReset(() => {
      this.epoch++;
      this.setData({ item: null, entries: [], loading: false });
    });
  },
  onUnload() {
    this.off();
    this.epoch++;
  },
  onShow() {
    void this.load();
  },
  async load() {
    if (
      !requireSession(
        '/packages/resident/pages/bill-detail/index?id=' + this.id,
      )
    )
      return;
    const epoch = ++this.epoch;
    this.setData({
      loading: true,
      error: '',
      item: null,
      entries: [],
      entryTotal: 0,
    });
    try {
      const item = await bill(this.id);
      if (epoch !== this.epoch) return;
      this.setData({
        item,
        amount: money(item.receivable_cents),
        settled: money(item.settled_cents),
        outstanding: money(item.outstanding_cents),
        hint: availability[item.payment_availability],
        canPay: ['available', 'own_payment_in_progress'].includes(
          item.payment_availability,
        ),
      });
      await this.loadEntries();
    } catch (error) {
      if (epoch === this.epoch)
        this.setData({ error: errorText(error), item: null });
    } finally {
      if (epoch === this.epoch) this.setData({ loading: false });
    }
  },
  async loadEntries(more = false) {
    if (!this.data.item || this.data.entryLoading) return;
    const epoch = this.epoch;
    this.setData({ entryLoading: true, entryError: '' });
    try {
      const page = more ? this.data.entryPage + 1 : 1;
      const result = await entries(this.id, page);
      if (epoch !== this.epoch) return;
      const rows = result.items.map((item) => ({
        id: item.id,
        label: entryLabels[item.display_type],
        amount: money(item.amount_cents),
        received: item.received_on || item.created_at.slice(0, 10),
      }));
      this.setData({
        entries: more ? [...this.data.entries, ...rows] : rows,
        entryPage: page,
        entryTotal: result.total,
      });
    } catch (error) {
      if (epoch === this.epoch) this.setData({ entryError: errorText(error) });
    } finally {
      if (epoch === this.epoch) this.setData({ entryLoading: false });
    }
  },
  more() {
    void this.loadEntries(true);
  },
  retryEntries() {
    void this.loadEntries();
  },
  pay() {
    const item = this.data.item;
    if (!item || !this.data.canPay) return;
    wx.navigateTo({
      url: item.own_payment_order_id
        ? paymentUrl(item.own_payment_order_id)
        : '/packages/resident/pages/payment-confirm/index?id=' + item.id,
    });
  },
});
