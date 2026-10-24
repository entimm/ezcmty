import * as api from '../../../../core/api';
import { currentCredential } from '../../../../core/session';
import { ApiError, errorText } from '../../../../core/request';
import { go, pageUrl } from '../../../../ui/navigation';
import type { Binding } from '../../../../core/types';
import { PageScope } from '../../page-state';
import { bindingView, loadAll } from '../../presentation';
Page({
  data: {
    signed: false,
    loading: false,
    loaded: false,
    error: '',
    filter: 'active',
    rows: [] as ReturnType<typeof bindingView>[],
  },
  scope: null as unknown as PageScope,
  records: [] as Binding[],
  onLoad() {
    this.scope = new PageScope();
    this.scope.watch(() => {
      this.records = [];
      this.setData({
        signed: false,
        loaded: false,
        rows: [],
        loading: false,
        error: '',
      });
    });
  },
  onShow() {
    if (!currentCredential()) {
      this.scope.leave();
      this.records = [];
      this.setData({
        signed: false,
        loaded: false,
        loading: false,
        rows: [],
        error: '',
      });
      return;
    }
    this.setData({ signed: true });
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
    if (!currentCredential()) {
      this.scope.leave();
      this.records = [];
      this.setData({
        signed: false,
        loaded: false,
        loading: false,
        rows: [],
        error: '',
      });
      return;
    }
    const valid = this.scope.next();
    this.setData({ loading: true, error: '' });
    try {
      const records = await loadAll((page) => api.bindings(page));
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
        .filter((binding) =>
          this.data.filter === 'active'
            ? binding.status === 'active'
            : binding.status !== 'active',
        )
        .map(bindingView),
    });
  },
  selectFilter(event: WechatMiniprogram.TouchEvent) {
    this.setData({ filter: event.currentTarget.dataset.filter });
    this.filterRows();
  },
  open(event: WechatMiniprogram.TouchEvent) {
    go('house-detail', { id: event.currentTarget.dataset.id });
  },
  claim() {
    if (this.data.signed) go('claim');
  },
  signIn() {
    go('login', { return_to: pageUrl('houses') });
  },
  showCurrent() {
    this.setData({ filter: 'active' });
    this.filterRows();
  },
});
