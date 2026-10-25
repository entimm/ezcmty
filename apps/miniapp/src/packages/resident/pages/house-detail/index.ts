import * as api from '../../../../core/api';
import { requireSession } from '../../../../core/session';
import { ApiError, errorText } from '../../../../core/request';
import { setSelectedBindingId } from '../../selection';
import { go, pageUrl } from '../../../../ui/navigation';
import { PageScope } from '../../page-state';
import { bindingView } from '../../presentation';
Page({
  data: {
    loading: false,
    error: '',
    binding: null as ReturnType<typeof bindingView> | null,
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
        binding: null,
        busy: false,
        confirming: false,
        loading: false,
      });
      if (visible) requireSession(pageUrl('house-detail', { id: this.id }));
    });
  },
  onShow() {
    if (!requireSession(pageUrl('house-detail', { id: this.id }))) {
      this.setData({ binding: null });
      return;
    }
    if (!this.scope.enter()) this.setData({ binding: null, confirming: false });
    this.setData({ busy: false });
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
      const binding = await api.binding(this.id);
      if (valid())
        this.setData({ binding: bindingView(binding), loading: false });
    } catch (error) {
      if (valid()) {
        if (error instanceof ApiError && [403, 404].includes(error.status))
          this.setData({ binding: null, confirming: false });
        this.setData({ loading: false, error: errorText(error) });
      }
    }
  },
  bills() {
    const binding = this.data.binding;
    if (!binding?.enabled) return;
    setSelectedBindingId(binding.id);
    go('bills');
  },
  orders() {
    go('payment-orders');
  },
  reclaim() {
    const binding = this.data.binding;
    if (binding)
      go('claim', {
        house_id: binding.house_id,
        community_id: binding.community_id,
      });
  },
  release() {
    if (this.data.binding?.status === 'active')
      this.setData({ confirming: true, actionError: '' });
  },
  close() {
    if (!this.data.busy) this.setData({ confirming: false });
  },
  async confirmRelease() {
    const binding = this.data.binding;
    if (!binding || binding.status !== 'active' || this.data.busy) return;
    const valid = this.scope.next();
    this.setData({ busy: true, actionError: '' });
    try {
      const updated = await api.releaseBinding(binding);
      if (valid()) {
        setSelectedBindingId(null);
        this.setData({
          binding: bindingView(updated),
          confirming: false,
          busy: false,
        });
        wx.showToast({ title: '房屋已解绑', icon: 'success' });
      }
    } catch (error) {
      if (valid()) {
        this.setData({ actionError: errorText(error), busy: false });
        await this.load();
      }
    }
  },
});
