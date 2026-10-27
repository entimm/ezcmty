import { requireIdentity } from '../../../../core/identities';
import { onContextReset } from '../../../../core/identities';
import { orders } from '../../api';
import { formatTime, money } from '../../../../core/format';
import { ApiError, errorText } from '../../../../core/request';
import { PaymentOrder } from '../../types';
import { go, pageUrl } from '../../../../ui/navigation';
import { paymentPresentation } from '../payment-detail/view';

type Filter = 'all' | 'success' | 'pending';
interface Row extends PaymentOrder {
  label: string;
  labelTone: string;
  amount: string;
  summary: string;
  created: string;
}
Page({
  data: {
    loading: true,
    moreLoading: false,
    error: '',
    moreError: '',
    filter: 'all' as Filter,
    items: [] as Row[],
    total: 0,
    page: 1,
    hasMore: false,
    scanned: 0,
  },
  epoch: 0,
  visible: false,
  off: () => {},
  onLoad() {
    this.off = onContextReset(() => {
      this.epoch++;
      this.setData({
        items: [],
        total: 0,
        loading: false,
        moreLoading: false,
        error: '登录状态已更新，请重新登录后继续。',
        moreError: '',
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
    this.setData({ loading: false, moreLoading: false });
  },
  onUnload() {
    this.visible = false;
    this.epoch++;
    this.off();
  },
  async load(more = false) {
    if (!requireIdentity('resident', pageUrl('payment-orders'))) return;
    if (
      more &&
      (this.data.loading || this.data.moreLoading || !this.data.hasMore)
    )
      return;
    const epoch = more ? this.epoch : ++this.epoch;
    let page = more ? this.data.page + 1 : 1;
    this.setData(
      more
        ? { moreLoading: true, moreError: '' }
        : { loading: true, error: '', moreError: '', moreLoading: false },
    );
    try {
      // Read one immutable created-at/id order. Splitting queries by mutable
      // status can miss an order while it moves between pending and payable.
      const pending = this.data.filter === 'pending';
      const batch: PaymentOrder[] = [];
      let total = 0;
      let hasMore = false;
      let scanned = more ? this.data.scanned : 0;
      for (let count = 0; count < (pending ? 5 : 1); count++) {
        const result = await orders(
          page,
          this.data.filter === 'success' ? 'succeeded' : '',
        );
        if (epoch !== this.epoch || !this.visible) return;
        total = result.total;
        scanned += result.items.length;
        hasMore = page * result.page_size < result.total;
        const matches = pending
          ? result.items.filter(
              (item) =>
                item.status !== 'closed' &&
                !(
                  item.status === 'succeeded' &&
                  item.confirmation_status === 'posted'
                ),
            )
          : result.items;
        batch.push(...matches);
        if (matches.length || !hasMore || count === 4) break;
        page++;
      }
      const rows: Row[] = batch.map((item) => {
        const presentation = paymentPresentation(item);
        return {
          ...item,
          label: presentation.label,
          labelTone: presentation.labelTone,
          amount: money(item.amount_cents),
          summary: item.items
            .map(
              (part) =>
                part.house_label_snapshot +
                ' · ' +
                part.billing_month.slice(0, 7).replace('-', '年') +
                '月',
            )
            .join('；'),
          created: formatTime(item.created_at),
        };
      });
      const unique = new Map(
        (more ? [...this.data.items, ...rows] : rows).map((item) => [
          item.id,
          item,
        ]),
      );
      const items = [...unique.values()].sort(
        (a, b) =>
          b.created_at.localeCompare(a.created_at) || b.id.localeCompare(a.id),
      );
      this.setData({
        items,
        // Pending totals are known only for the pages actually inspected.
        total: pending ? items.length : total,
        page,
        hasMore,
        scanned,
      });
    } catch (error) {
      if (epoch === this.epoch && this.visible) {
        if (error instanceof ApiError && [401, 403].includes(error.status))
          this.setData({
            error: errorText(error),
            items: [],
            total: 0,
            hasMore: false,
          });
        else
          this.setData(
            more
              ? { moreError: errorText(error) }
              : { error: errorText(error) },
          );
      }
    } finally {
      if (epoch === this.epoch && this.visible)
        this.setData({ loading: false, moreLoading: false });
    }
  },
  filter(event: WechatMiniprogram.TouchEvent) {
    const filter: string = event.currentTarget.dataset.filter;
    if (
      !['all', 'success', 'pending'].includes(filter) ||
      filter === this.data.filter
    )
      return;
    this.setData({
      filter: filter as Filter,
      items: [],
      total: 0,
      page: 1,
      hasMore: false,
      scanned: 0,
    });
    void this.load();
  },
  retry() {
    void this.load();
  },
  more() {
    void this.load(true);
  },
  open(event: WechatMiniprogram.TouchEvent) {
    go('payment-detail', { id: event.currentTarget.dataset.id });
  },
  emptyAction() {
    if (this.data.filter === 'all') go('bills');
    else {
      this.setData({ filter: 'all' });
      void this.load();
    }
  },
});
