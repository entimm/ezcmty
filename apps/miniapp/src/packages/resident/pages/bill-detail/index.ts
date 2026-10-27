import { requireIdentity } from '../../../../core/identities';
import { onContextReset } from '../../../../core/identities';
import { bill, entries } from '../../api';
import { formatTime, money } from '../../../../core/format';
import { ApiError, errorText } from '../../../../core/request';
import { ResidentBill } from '../../types';
import { go, pageUrl } from '../../../../ui/navigation';
import { billPresentation } from '../payment-detail/view';

interface EntryRow {
  id: string;
  label: string;
  amount: string;
  received: string;
  registered: string;
  orderId: string | null;
}
Page({
  data: {
    loading: true,
    error: '',
    item: null as ResidentBill | null,
    month: '',
    receivable: '',
    settled: '',
    outstanding: '',
    label: '',
    tone: '',
    hint: '',
    warning: false,
    canPay: false,
    paid: false,
    button: '',
    entries: [] as EntryRow[],
    entryLoading: false,
    entryError: '',
    entryPage: 1,
    entryTotal: 0,
    entriesMore: false,
  },
  id: '',
  epoch: 0,
  visible: false,
  off: () => {},
  onLoad(options) {
    this.id = options.id || '';
    this.off = onContextReset(() => {
      this.epoch++;
      this.setData({
        item: null,
        entries: [],
        loading: false,
        entryLoading: false,
        error: '登录状态已更新，请重新登录后继续。',
        entryError: '',
      });
    });
  },
  onShow() {
    this.visible = true;
    void this.load();
  },
  async onPullDownRefresh() {
    try {
      await this.load();
    } finally {
      wx.stopPullDownRefresh();
    }
  },
  onHide() {
    this.visible = false;
    this.epoch++;
    this.setData({ loading: false, entryLoading: false });
  },
  onUnload() {
    this.visible = false;
    this.epoch++;
    this.off();
  },
  async load() {
    if (!requireIdentity('resident', pageUrl('bill-detail', { id: this.id })))
      return;
    const epoch = ++this.epoch;
    this.setData({
      loading: true,
      error: '',
      item: null,
      entries: [],
      entryLoading: false,
      entryError: '',
      entryPage: 1,
      entryTotal: 0,
      entriesMore: false,
    });
    try {
      const item = await bill(this.id);
      if (epoch !== this.epoch || !this.visible) return;
      this.setData({
        item,
        ...billPresentation(item),
        month: item.billing_month.slice(0, 7).replace('-', '年') + '月',
        receivable: money(item.receivable_cents),
        settled: money(item.settled_cents),
        outstanding: money(item.outstanding_cents),
        loading: false,
      });
      await this.readEntries();
    } catch (error) {
      if (epoch === this.epoch && this.visible)
        this.setData({ error: errorText(error), item: null });
    } finally {
      if (epoch === this.epoch && this.visible)
        this.setData({ loading: false });
    }
  },
  async readEntries(more = false) {
    if (!this.data.item || this.data.entryLoading || !this.visible) return;
    const epoch = this.epoch;
    const page = more ? this.data.entryPage + 1 : 1;
    this.setData({ entryLoading: true, entryError: '' });
    try {
      const result = await entries(this.id, page);
      if (epoch !== this.epoch || !this.visible) return;
      const labels = {
        own_payment: '本人缴纳',
        other_payment: '其他缴费人缴纳',
        offline_receipt: '线下登记',
        offline_adjustment: '线下登记调整',
      };
      const rows: EntryRow[] = result.items.map((entry) => ({
        id: entry.id,
        label: labels[entry.display_type],
        amount: money(entry.amount_cents),
        received: entry.received_on || '未提供',
        registered: formatTime(entry.created_at),
        orderId:
          entry.display_type === 'own_payment'
            ? entry.own_payment_order_id
            : null,
      }));
      this.setData({
        entries: more ? [...this.data.entries, ...rows] : rows,
        entryPage: page,
        entryTotal: result.total,
        entriesMore: page * result.page_size < result.total,
      });
    } catch (error) {
      if (epoch === this.epoch && this.visible) {
        if (error instanceof ApiError && [403, 404].includes(error.status))
          this.setData({
            item: null,
            entries: [],
            entryTotal: 0,
            entriesMore: false,
            error: errorText(error),
          });
        else this.setData({ entryError: errorText(error) });
      }
    } finally {
      if (epoch === this.epoch && this.visible)
        this.setData({ entryLoading: false });
    }
  },
  moreEntries() {
    void this.readEntries(true);
  },
  retryEntries() {
    void this.readEntries(this.data.entries.length > 0);
  },
  pay() {
    const item = this.data.item;
    if (this.data.loading || !item || !this.data.canPay) return;
    go(item.own_payment_order_id ? 'payment-detail' : 'payment-confirm', {
      id: item.own_payment_order_id || item.id,
    });
  },
  openOrder(event: WechatMiniprogram.TouchEvent) {
    const entry = this.data.entries.find(
      (value) => value.id === event.currentTarget.dataset.id,
    );
    if (entry?.orderId) go('payment-detail', { id: entry.orderId });
  },
  records() {
    go('payment-orders');
  },
});
