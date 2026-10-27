import { requireIdentity } from '../../../../core/identities';
import * as api from '../../api';
import { ApiError, errorText } from '../../../../core/request';
import { go, pageUrl } from '../../../../ui/navigation';
import { PageScope } from '../../page-state';
import { claimView, loadAll } from '../../presentation';
Page({
  data: {
    loading: false,
    error: '',
    claim: null as ReturnType<typeof claimView> | null,
    confirming: false,
    busy: false,
    actionError: '',
  },
  id: '',
  scope: null as unknown as PageScope,
  onLoad(options: Record<string, string>) {
    this.scope = new PageScope();
    this.id = options.id || '';
    this.scope.watch((visible) => {
      this.setData({
        claim: null,
        busy: false,
        confirming: false,
        loading: false,
      });
      if (visible)
        requireIdentity('resident', pageUrl('claim-detail', { id: this.id }));
    });
  },
  onShow() {
    if (
      !requireIdentity('resident', pageUrl('claim-detail', { id: this.id }))
    ) {
      this.setData({ claim: null });
      return;
    }
    if (!this.scope.enter()) this.setData({ claim: null });
    this.setData({ busy: false, confirming: false });
    void this.load();
  },
  onHide() {
    this.scope.leave();
    this.setData({ confirming: false });
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
      const claim = await api.claim(this.id);
      if (valid()) this.setData({ claim: claimView(claim), loading: false });
    } catch (error) {
      if (valid()) {
        if (error instanceof ApiError && [403, 404].includes(error.status))
          this.setData({ claim: null, confirming: false });
        this.setData({ loading: false, error: errorText(error) });
      }
    }
  },
  withdraw() {
    if (this.data.claim?.status === 'pending')
      this.setData({ confirming: true, actionError: '' });
  },
  close() {
    if (!this.data.busy) this.setData({ confirming: false });
  },
  async confirmWithdraw() {
    const claim = this.data.claim;
    if (!claim || claim.status !== 'pending' || this.data.busy) return;
    const valid = this.scope.next();
    this.setData({ busy: true, actionError: '' });
    try {
      const updated = await api.cancelClaim(claim);
      if (valid()) {
        this.setData({
          claim: claimView(updated),
          confirming: false,
          busy: false,
        });
        wx.showToast({ title: '申请已撤回', icon: 'success' });
      }
    } catch (error) {
      if (valid()) {
        this.setData({ actionError: errorText(error), busy: false });
        await this.load();
      }
    }
  },
  async binding() {
    const claim = this.data.claim;
    if (!claim || claim.status !== 'approved' || this.data.busy) return;
    const valid = this.scope.next();
    this.setData({ busy: true, actionError: '' });
    try {
      const bindings = await loadAll((page) => api.bindings(page));
      if (!valid()) return;
      const binding = bindings.find(
        (item) => item.claim_application_id === claim.id,
      );
      this.setData({ busy: false });
      if (binding) go('house-detail', { id: binding.id });
      else
        this.setData({
          actionError: '未找到当前房屋授权，请到我的房屋查看或联系物业。',
        });
    } catch (error) {
      if (valid()) this.setData({ busy: false, actionError: errorText(error) });
    }
  },
  reclaim() {
    const claim = this.data.claim;
    if (claim)
      go('claim', {
        house_id: claim.house_id,
        community_id: claim.community_id,
      });
  },
  home() {
    go('home');
  },
});
