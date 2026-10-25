import * as api from '../../../../core/api';
import { currentCredential } from '../../../../core/session';
import { ApiError, errorText } from '../../../../core/request';
import { money } from '../../../../core/format';
import { getSelectedBindingId, setSelectedBindingId } from '../../selection';
import type { Binding } from '../../../../core/types';
import { go, pageUrl } from '../../../../ui/navigation';
import { PageScope } from '../../page-state';
import { bindingView, claimView, loadAll } from '../../presentation';

Page({
  data: {
    signed: false,
    loading: false,
    loaded: false,
    error: '',
    summaryError: '',
    summaryLoading: false,
    available: [] as Binding[],
    selected: null as ReturnType<typeof bindingView> | null,
    pending: [] as ReturnType<typeof claimView>[],
    bindingCount: 0,
    amount: '0.00',
    billCount: 0,
    overdue: false,
    picker: false,
  },
  scope: null as unknown as PageScope,
  onLoad() {
    this.scope = new PageScope();
    this.scope.watch(() =>
      this.setData({
        signed: false,
        loaded: true,
        loading: false,
        available: [],
        selected: null,
        pending: [],
        bindingCount: 0,
        picker: false,
        amount: '0.00',
        error: '',
      }),
    );
  },
  onShow() {
    const signed = !!currentCredential();
    const sameOwner = this.scope.enter();
    if (!sameOwner)
      this.setData({
        loaded: false,
        available: [],
        selected: null,
        pending: [],
        bindingCount: 0,
        error: '',
        summaryError: '',
        amount: '0.00',
        billCount: 0,
        picker: false,
      });
    this.setData({ signed });
    if (signed) void this.load();
    else this.setData({ loaded: true, loading: false });
  },
  onHide() {
    this.scope.leave();
    this.setData({ picker: false });
  },
  onUnload() {
    this.scope.dispose();
  },
  onPullDownRefresh() {
    void this.load().finally(() => wx.stopPullDownRefresh());
  },
  async load() {
    if (!currentCredential()) return;
    const valid = this.scope.next();
    this.setData({ loading: true, error: '' });
    try {
      const [bindings, claims] = await Promise.all([
        loadAll((page) => api.bindings(page)),
        loadAll((page) => api.claims(page, 'pending')),
      ]);
      if (!valid()) return;
      const available = bindings.filter(
        (b) => b.status === 'active' && b.effective_enabled,
      );
      const selected =
        available.find((b) => b.id === getSelectedBindingId()) ||
        available[0] ||
        null;
      setSelectedBindingId(selected?.id || null);
      this.setData({
        available,
        selected: selected ? bindingView(selected) : null,
        pending: claims.map(claimView),
        bindingCount: bindings.length,
        loaded: true,
        loading: false,
        summaryLoading: !!selected,
        summaryError: '',
      });
      if (selected) {
        try {
          const bills = await loadAll((page) => api.bills(selected.id, page));
          if (valid())
            this.setData({
              amount: money(
                bills.reduce((sum, bill) => sum + bill.outstanding_cents, 0),
              ),
              billCount: bills.length,
              overdue: bills.some((bill) => bill.is_overdue),
              summaryLoading: false,
            });
        } catch (error) {
          if (valid())
            this.setData({
              summaryError: errorText(error),
              summaryLoading: false,
            });
        }
      }
    } catch (error) {
      if (valid()) {
        if (error instanceof ApiError && [403, 404].includes(error.status))
          this.setData({
            loaded: false,
            available: [],
            selected: null,
            pending: [],
            picker: false,
          });
        this.setData({ loading: false, error: errorText(error) });
      }
    }
  },
  openPicker() {
    if (this.data.available.length > 1) this.setData({ picker: true });
  },
  closePicker() {
    this.setData({ picker: false });
  },
  selectHouse(event: WechatMiniprogram.CustomEvent<{ binding: Binding }>) {
    const binding = this.data.available.find(
      (b) => b.id === event.detail.binding.id,
    );
    if (!binding) return;
    setSelectedBindingId(binding.id);
    this.setData({ picker: false });
    void this.load();
  },
  profile() {
    go('profile');
  },
  bills() {
    go('bills');
  },
  houses() {
    go('houses');
  },
  claims() {
    go('claims');
  },
  orders() {
    go('payment-orders');
  },
  claim() {
    go(
      this.data.signed ? 'claim' : 'login',
      this.data.signed ? undefined : { return_to: pageUrl('claim') },
    );
  },
  pendingDetail() {
    const claim = this.data.pending[0];
    if (claim) go('claim-detail', { id: claim.id });
  },
  houseDetail() {
    if (this.data.selected) go('house-detail', { id: this.data.selected.id });
  },
});
