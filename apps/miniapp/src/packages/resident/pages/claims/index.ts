import * as api from '../../../../core/api';
import { requireSession } from '../../../../core/session';
import { ApiError, errorText } from '../../../../core/request';
import { go, pageUrl } from '../../../../ui/navigation';
import type { Claim } from '../../../../core/types';
import { PageScope } from '../../page-state';
import { claimView, loadAll } from '../../presentation';
Page({
  data: {
    loading: false,
    loaded: false,
    error: '',
    filter: 'all',
    rows: [] as ReturnType<typeof claimView>[],
  },
  scope: null as unknown as PageScope,
  records: [] as Claim[],
  onLoad() {
    this.scope = new PageScope();
    this.scope.watch((visible) => {
      this.records = [];
      this.setData({ loaded: false, rows: [], loading: false, error: '' });
      if (visible) requireSession(pageUrl('claims'));
    });
  },
  onShow() {
    if (!requireSession(pageUrl('claims'))) {
      this.setData({ loaded: false, rows: [] });
      return;
    }
    if (!this.scope.enter()) {
      this.records = [];
      this.setData({ loaded: false, rows: [] });
    }
    void this.load();
  },
  onHide() {
    this.scope.leave();
  },
  onUnload() {
    this.scope.dispose();
  },
  onPullDownRefresh() {
    void this.load().finally(() => wx.stopPullDownRefresh());
  },
  async load() {
    const valid = this.scope.next();
    this.setData({ loading: true, error: '' });
    try {
      const records = await loadAll((page) => api.claims(page));
      if (!valid()) return;
      this.records = records;
      this.setData({ loading: false, loaded: true });
      this.filterRows();
    } catch (error) {
      if (valid()) {
        if (error instanceof ApiError && [403, 404].includes(error.status)) {
          this.records = [];
          this.setData({ rows: [], loaded: false });
        }
        this.setData({ loading: false, error: errorText(error) });
      }
    }
  },
  filterRows() {
    this.setData({
      rows: this.records
        .filter(
          (claim) =>
            this.data.filter === 'all' ||
            (this.data.filter === 'pending'
              ? claim.status === 'pending'
              : claim.status !== 'pending'),
        )
        .map(claimView),
    });
  },
  selectFilter(event: WechatMiniprogram.TouchEvent) {
    this.setData({ filter: event.currentTarget.dataset.filter });
    this.filterRows();
  },
  open(event: WechatMiniprogram.TouchEvent) {
    go('claim-detail', { id: event.currentTarget.dataset.id });
  },
  claim() {
    go('claim');
  },
  showAll() {
    this.setData({ filter: 'all' });
    this.filterRows();
  },
});
